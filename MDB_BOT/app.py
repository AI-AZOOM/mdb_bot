import re
import asyncio
import logging
import os 
from telethon import TelegramClient, events
from telethon.tl.types import MessageEntityTextUrl

# Configure logging
logging.basicConfig(level=logging.INFO, format='[%(levelname)s] %(asctime)s - %(message)s')

# ----------------------------------------------------------------------
# --- MODIFIED: Read credentials securely from Environment Variables ---
# ----------------------------------------------------------------------
api_id = None
api_hash = None
phone_number = None

try:
    # Get values from environment (e.g., set on Render)
    api_id_str = os.environ.get('API_ID')
    if api_id_str:
        api_id = int(api_id_str)
    
    api_hash = os.environ.get('API_HASH')
    phone_number = os.environ.get('PHONE_NUMBER')
    
except Exception as e:
    logging.error(f"FATAL ERROR during Environment Variable parsing: {e}")
    
# --- Channel/Bot/Group Constants ---
channel_a_username = 'solwhaletrending'   # Solana, long pipeline source (Requires 🔥 prefix)
channel_b_username = 'AveSignalMonitor'   # BNB (EVM), short pipeline source (Requires 🪙 prefix)
# ---------------------------------------------------
soul_scanner_bot_username = 'soul_scanner_bot'
phanes_bot_bot_username = 'PhanesRedBot'

# ----------------------------------------------------------------------------------
# !!! TARGET GROUP ASSIGNMENTS !!!
# ----------------------------------------------------------------------------------
sol_target_group = -4920907358 # Destination for Solana CAs
bnb_target_group = -4982124188 # Destination for BNB CAs
# ----------------------------------------------------------------------------------

# Regular expressions for different chain addresses
solana_address_pattern = re.compile(r'[1-9A-HJ-NP-Za-km-z]{32,44}')
evm_address_pattern = re.compile(r'0x[a-fA-F0-9]{40}') 

# Global variable to store the contract address (CA) and its current state.
pending_ca_for_analysis = {} 
# Format: { 'CA_ADDRESS': 'current_state' }

def is_valid_solana_address(address: str) -> bool:
    """Checks if a string is a valid Solana public key (only called for Solana source)."""
    try:
        from solders.pubkey import Pubkey
        Pubkey.from_string(address)
        return True
    except Exception:
        return False

# Create a client that will log in as a regular user, not a bot.
client = TelegramClient('session_user', api_id, api_hash)

async def main():
    """Main asynchronous function to start the userbot and handle messages."""
    # Check if necessary credentials were loaded from environment variables
    if not all([api_id, api_hash, phone_number]):
        logging.error("Exiting: Missing critical environment variables (API_ID, API_HASH, or PHONE_NUMBER). Please set them correctly.")
        return # Exits the main function safely

    await client.start(phone=phone_number)
    
    logging.info(f"Userbot started. Listening to {channel_a_username} (SOL) and {channel_b_username} (BNB)...")

    # Helper function to find CA in a message based on the source channel
    def extract_ca(event, is_bnb_channel: bool):
        pattern = evm_address_pattern if is_bnb_channel else solana_address_pattern
        found_ca = None
        
        # 1. Search in URL entities first
        if event.message.entities:
            for entity in event.message.entities:
                if isinstance(entity, MessageEntityTextUrl):
                    matches = pattern.findall(entity.url)
                    for addr in matches:
                        # For Solana, validate with solders
                        if not is_bnb_channel and is_valid_solana_address(addr):
                            return addr
                        # For BNB/EVM, a regex match is usually enough
                        elif is_bnb_channel:
                            return addr
                if found_ca: break

        # 2. Search in raw message text
        if not found_ca:
            matches = pattern.findall(event.raw_text)
            if matches:
                for addr in matches:
                    if not is_bnb_channel and is_valid_solana_address(addr):
                        return addr
                    elif is_bnb_channel:
                        return addr
                        
        return None

    # ----------------------------------------------------------------------------------
    # PIPELINE A (solwhaletrending) - Solana, long pipeline: Soul Scanner -> /th -> /tt
    # ----------------------------------------------------------------------------------
    @client.on(events.NewMessage(chats=channel_a_username))
    async def sol_handler(event):
        """STEP A1: MONITOR SOLANA CHANNEL & SEND CA TO SOUL SCANNER (Only if starts with 🔥)."""
        
        raw_text = event.raw_text.strip()
        # --- SOLANA FILTER: CHECK FOR 🔥 START ---
        if not raw_text.startswith('🔥'):
            logging.info(f"Pipeline A Skip: Message from {channel_a_username} did not start with '🔥'.")
            return
        # ------------------------------------------
        
        found_ca_to_send = extract_ca(event, is_bnb_channel=False) 
        
        if found_ca_to_send:
            if found_ca_to_send in pending_ca_for_analysis:
                logging.warning(f"CA {found_ca_to_send} is already in the pipeline. Skipping.")
                return
            pending_ca_for_analysis[found_ca_to_send] = 'a_soul_scanner'
            logging.info(f"Pipeline A START: Found SOLANA CA {found_ca_to_send}. Sending to soul scanner bot.")
            await client.send_message(soul_scanner_bot_username, found_ca_to_send)
        else:
            logging.info("Pipeline A Skip: Valid Solana CA not found in the message.")

    @client.on(events.NewMessage(chats=soul_scanner_bot_username))
    async def sol_soul_scanner_handler(event):
        """STEP A2: WAIT FOR SOUL SCANNER RESPONSE & SEND /TH COMMAND."""
        found_ca = None
        for ca, state in pending_ca_for_analysis.items():
            if state == 'a_soul_scanner' and ca in event.raw_text:
                found_ca = ca
                break
        if not found_ca: return

        pending_ca_for_analysis[found_ca] = 'a_waiting_for_th_response'
        logging.info(f"Pipeline A Step 2: Received response for {found_ca} from Soul Scanner. Sending /th command to Phanes bot.")
        await client.send_message(phanes_bot_bot_username, f"/th {found_ca}")

    @client.on(events.NewMessage(chats=phanes_bot_bot_username))
    async def sol_phanes_th_response_handler(event):
        """STEP A3: WAIT FOR PHANES /TH RESPONSE & SEND /TT COMMAND."""
        found_ca = None
        for ca, state in pending_ca_for_analysis.items():
            if state == 'a_waiting_for_th_response':
                found_ca = ca
                break
            
        if not found_ca: return
            
        logging.info(f"Pipeline A Step 3: Assuming /th response for {found_ca}. IMMEDIATELY sending /tt command.")
        pending_ca_for_analysis[found_ca] = 'a_waiting_for_tt_response'
        await client.send_message(phanes_bot_bot_username, f"/tt {found_ca}")
        raise events.StopPropagation 
        
    @client.on(events.NewMessage(chats=phanes_bot_bot_username))
    async def sol_phanes_tt_response_handler(event):
        """STEP A4: WAIT FOR PHANES /TT RESPONSE & FORWARD CA TO FINAL GROUP."""
        found_ca = None
        for ca, state in pending_ca_for_analysis.items():
            if state == 'a_waiting_for_tt_response':
                found_ca = ca
                break
        
        if not found_ca: return

        logging.info(f"Pipeline A Final Step: Forwarding CA {found_ca} to {sol_target_group}.")
        try:
            # --- USING SOLANA TARGET GROUP ---
            await client.send_message(sol_target_group, found_ca) 
            logging.info(f"Pipeline SUCCESS: CA {found_ca} forwarded to {sol_target_group}.")
        except Exception as e:
            logging.error(f"Pipeline ERROR (A): Failed to send message to target group {sol_target_group}: {e}")

        if found_ca in pending_ca_for_analysis:
            del pending_ca_for_analysis[found_ca]
            

    # ----------------------------------------------------------------------------------
    # PIPELINE B (AveSignalMonitor) - BNB/EVM, short pipeline: Phanes -> /tt
    # ----------------------------------------------------------------------------------
    @client.on(events.NewMessage(chats=channel_b_username))
    async def bnb_handler(event):
        """STEP B1: MONITOR BNB CHANNEL & SEND CA DIRECTLY TO PHANES (Only if starts with 🪙)."""
        
        raw_text = event.raw_text.strip()
        # --- BNB FILTER: CHECK FOR 🪙 START ---
        if not raw_text.startswith('🪙'):
            logging.info(f"Pipeline B Skip: Message from {channel_b_username} did not start with '🪙'.")
            return
        # ------------------------------------------

        found_ca_to_send = extract_ca(event, is_bnb_channel=True) 

        if found_ca_to_send:
            if found_ca_to_send in pending_ca_for_analysis:
                logging.warning(f"CA {found_ca_to_send} is already in the pipeline. Skipping.")
                return

            pending_ca_for_analysis[found_ca_to_send] = 'b_waiting_for_response'
            logging.info(f"Pipeline B START: Found BNB CA {found_ca_to_send}. Sending CA directly to Phanes bot.")
            
            await client.send_message(phanes_bot_bot_username, found_ca_to_send)
        else:
            logging.info("Pipeline B Skip: Valid BNB/EVM CA not found in the message.")

    @client.on(events.NewMessage(chats=phanes_bot_bot_username))
    async def bnb_phanes_initial_response_handler(event):
        """STEP B2: WAIT FOR INITIAL PHANES RESPONSE & SEND /TT COMMAND."""
        found_ca = None
        for ca, state in pending_ca_for_analysis.items():
            if state == 'b_waiting_for_response':
                found_ca = ca
                break
                    
        if not found_ca: return

        logging.info(f"Pipeline B Step 2: Assuming initial response for {found_ca}. IMMEDIATELY sending /tt command.")
        pending_ca_for_analysis[found_ca] = 'b_waiting_for_tt_response'
        
        await client.send_message(phanes_bot_bot_username, f"/tt {found_ca}")
            
        raise events.StopPropagation
        

    @client.on(events.NewMessage(chats=phanes_bot_bot_username))
    async def bnb_phanes_tt_response_handler(event):
        """STEP B3: WAIT FOR PHANES /TT RESPONSE & FORWARD CA TO FINAL GROUP."""
        found_ca = None
        for ca, state in pending_ca_for_analysis.items():
            if state == 'b_waiting_for_tt_response':
                found_ca = ca
                break
        
        if not found_ca: return

        logging.info(f"Pipeline B Final Step: Forwarding CA {found_ca} to {bnb_target_group}.")
        try:
            # --- USING BNB TARGET GROUP ---
            await client.send_message(bnb_target_group, found_ca) 
            logging.info(f"Pipeline SUCCESS: CA {found_ca} forwarded to {bnb_target_group}.")
        except Exception as e:
            logging.error(f"Pipeline ERROR (B): Failed to send message to target group {bnb_target_group}: {e}")

        if found_ca in pending_ca_for_analysis:
            del pending_ca_for_analysis[found_ca]
        
    await client.run_until_disconnected()

if __name__ == '__main__':
    print("NOTE: Ensure 'solders' is installed (`pip install solders`).")
    print("CRITICAL FIX: Channel source usernames updated. Solana source: @solwhaletrending (filtered by 🔥). BNB source: @AveSignalMonitor (filtered by 🪙).")
    asyncio.run(main())