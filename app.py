from flask import Flask, request, jsonify, render_template, session
import google.generativeai as genai
import os
from dotenv import load_dotenv
from difflib import get_close_matches
import logging
from datetime import datetime, timedelta
from flask_limiter import Limiter
from flask_limiter.util import get_remote_address
import random
import json
import traceback # Import traceback for detailed error logging

# --- Setup ---

# Load environment variables FIRST to ensure they are available for all configurations
load_dotenv()

app = Flask(__name__)

# Configuration
app.secret_key = os.getenv("FLASK_SECRET_KEY")
if not app.secret_key:
    logging.warning("FLASK_SECRET_KEY environment variable not set. Using a default fallback key. "
                    "Ensure this is set for production for security reasons.")
    app.secret_key = "super_secret_fallback_key_for_dev" # Use a strong, random key in production!

# Logging
os.makedirs("logs", exist_ok=True)
logging.basicConfig(
    filename=f"logs/chatbot_{datetime.now().strftime('%Y%m%d')}.log",
    level=logging.DEBUG, # Set to DEBUG for more detailed logging during development/debugging
    format='%(asctime)s | %(levelname)s | %(message)s',
    datefmt='%Y-%m-%d %H:%M:%S'
)
logging.getLogger().setLevel(logging.DEBUG) # Redundant with basicConfig level, but doesn't hurt.

# Rate limiting
limiter = Limiter(
    app=app,
    key_func=get_remote_address,
    storage_uri="memory://", # In-memory storage means limits reset on service restart
    default_limits=["200 per day", "50 per hour"]
)

# Gemini AI Configuration - CRITICAL SECTION
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")

if not GEMINI_API_KEY:
    logging.critical("FATAL ERROR: GEMINI_API_KEY environment variable is not set. "
                     "The chatbot will not be able to function without a valid API key.")
    # In a production environment, you might want to raise an exception here
    # to prevent the app from even starting if a critical dependency is missing.
    # raise ValueError("GEMINI_API_KEY is not set. Cannot start chatbot.")
    model = None # Ensure model is None if API key is missing
else:
    try:
        genai.configure(api_key=GEMINI_API_KEY)
        logging.info("Gemini API key successfully configured.")
        model = genai.GenerativeModel("models/gemini-1.5-flash") # Or "models/gemini-pro"
        logging.info(f"Gemini GenerativeModel '{model.model_name}' initialized.")
    except Exception as e:
        logging.critical(f"FATAL ERROR: Failed to configure or initialize Gemini AI model: {e}")
        logging.critical(traceback.format_exc()) # Log the full traceback
        model = None # Set model to None if initialization fails

# --- Data Stores ---
PRODUCTS = {
    "1) Hydrating Milky Cleanser": {"name": "Hydrating Milky Cleanser", "price": 399, "stock": 50},
    "2) Hyaluronic Acid Serum": {"name": "Hyaluronic Acid Serum", "price": 899, "stock": 40},
    "3) Ceramide Moisturizer": {"name": "Ceramide Moisturizer", "price": 599, "stock": 35},
    "4) Oil-Control Foaming Facewash": {"name": "Oil-Control Foaming Facewash", "price": 349, "stock": 50},
    "5) pH-Balanced Gel Cleanser": {"name": "pH-Balanced Gel Cleanser", "price": 449, "stock": 50},
    "6) Multi Vitamin Serum": {"name": "Multi-Vitamin Serum", "price": 849, "stock": 35},
    "7) Lightweight Moisturizer": {"name": "Lightweight Moisturizer", "price": 549, "stock": 40},
    "8) Fragrance-Free Cream Cleanser": {"name": "Fragrance-Free Cream Cleanser", "price": 499, "stock": 45},
    "9) Calming Serum": {"name": "Calming Serum", "price": 899, "stock": 30},
    "10) Barrier Repair Cream": {"name": "Barrier Repair Cream", "price": 649, "stock": 35},
}

# Order storage with persistence (Note: On Render free tier, this will reset on deploy/idle)
ORDERS_FILE = "orders.json"

def load_orders():
    try:
        if os.path.exists(ORDERS_FILE):
            with open(ORDERS_FILE, 'r') as f:
                loaded_orders = json.load(f)
                logging.info(f"Loaded {len(loaded_orders)} orders from {ORDERS_FILE}")
                return loaded_orders
        else:
            logging.info(f"Orders file {ORDERS_FILE} not found. Starting with empty orders.")
            return {}
    except json.JSONDecodeError as e:
        logging.error(f"Error decoding {ORDERS_FILE}: {e}")
        logging.error(traceback.format_exc())
        return {}
    except Exception as e:
        logging.error(f"Unexpected error loading orders from {ORDERS_FILE}: {e}")
        logging.error(traceback.format_exc())
        return {}


def save_orders():
    try:
        with open(ORDERS_FILE, 'w') as f:
            json.dump(orders, f, indent=4)
            logging.info(f"Saved {len(orders)} orders to {ORDERS_FILE}")
    except Exception as e:
        logging.error(f"Error saving orders to {ORDERS_FILE}: {e}")
        logging.error(traceback.format_exc())

orders = load_orders()


# --- Helper Functions ---
def generate_order_id():
    return f"BEAUTY{random.randint(1000, 9999)}"


def create_delivery_date():
    return (datetime.now() + timedelta(days=3)).strftime("%d %b %Y")


def update_order_status():
    """Simulate status changes over time"""
    orders_changed = False
    for order_id in orders:
        original_status = orders[order_id]["status"]
        if orders[order_id]["status"] == "Confirmed":
            if random.random() > 0.7:  # 30% chance to advance status
                orders[order_id]["status"] = "Shipped"
                orders_changed = True
        elif orders[order_id]["status"] == "Shipped":
            if random.random() > 0.8:  # 20% chance to deliver
                orders[order_id]["status"] = "Delivered"
                orders_changed = True
        if original_status != orders[order_id]["status"]:
            logging.info(f"Order {order_id} status changed from {original_status} to {orders[order_id]['status']}")
    if orders_changed:
        save_orders()


FAQS = {
    # ==== Core Product Categories ====
    "Hi": """Hi there!💖 I'm BeautyBot. Need help with skincare?
    You can:
    – Ask about products
    – Place an order (like: order sunscreen)
    – Track an order (try: where is my order?)""",
    "Hello ": """Hello! BeautyBot here 💖
    Ask me about skincare products,
    Place an order (e.g., order sunscreen),
    Or track one (e.g., where is my order).""",
    "products you sell": "We offer:\n\n"
                         "🧴 *Cleansers*: Foaming, Milky, Gel\n"
                         "☀ *Sunscreens*: SPF 30/50, Matte, Mineral\n"
                         "💧 *Serums*: Vitamin C, Hyaluronic Acid, Retinol\n"
                         "🌿 *Toners*: Hydrating, Exfoliating (AHA/BHA)\n"
                         "🧴 *Moisturizers*: Gel, Cream, Oil-Free\n"
                         "🛡 *Eye Creams*: Dark Circles, Puffiness\n"
                         "🧖 *Masks*: Clay, Sheet, Overnight\n"
                         "✨ *Exfoliators*: Scrubs, Chemical Peels",

    # ==== Product Recommendations ====
    "what is best for dry skin": "Try our:\n"
                                 "- Hydrating Milky Cleanser (₹399)\n"
                                 "- Hyaluronic Acid Serum (₹899)\n"
                                 "- Ceramide Moisturizer (₹599)",
    "recommend product for dry skin": "Try our:\n"
                                      "- Hydrating Milky Cleanser (₹399)\n"
                                      "- Hyaluronic Acid Serum (₹899)\n"
                                      "- Ceramide Moisturizer (₹599)",
    "good product for dry skin": "Try our:\n"
                                 "- Hydrating Milky Cleanser (₹399)\n"
                                 "- Hyaluronic Acid Serum (₹899)\n"
                                 "- Ceramide Moisturizer (₹599)",
    "what is best for oily skin": "Recommended:\n"
                                  "- Oil-Control Foaming Facewash (₹349)\n"
                                  "- Niacinamide Serum (₹799)\n"
                                  "- Matte Sunscreen SPF 50 (₹599)",
    "recommend product for oily skin": "Recommended:\n"
                                       "- Oil-Control Foaming Facewash (₹349)\n"
                                       "- Niacinamide Serum (₹799)\n"
                                       "- Matte Sunscreen SPF 50 (₹599)",
    "good product for oily skin": "Recommended:\n"
                                  "- Oil-Control Foaming Facewash (₹349)\n"
                                  "- Niacinamide Serum (₹799)\n"
                                  "- Matte Sunscreen SPF 50 (₹599)",
    "what is best for acne-prone skin": "Clarifying solutions:\n"
                                        "- Salicylic Acid Cleanser (₹379)\n"
                                        "- BHA Exfoliating Toner (₹699)\n"
                                        "- Oil-Free Moisturizer (₹529)",
    "recommend product for acne-prone skin": "Clarifying solutions:\n"
                                             "- Salicylic Acid Cleanser (₹379)\n"
                                             "- BHA Exfoliating Toner (₹699)\n"
                                             "- Oil-Free Moisturizer (₹529)",
    "good product for acne-prone skin": "Clarifying solutions:\n"
                                        "- Salicylic Acid Cleanser (₹379)\n"
                                        "- BHA Exfoliating Toner (₹699)\n"
                                        "- Oil-Free Moisturizer (₹529)",
    "what is best for combination skin": "Perfect balance:\n"
                                         "- pH-Balanced Gel Cleanser (₹449)\n"
                                         "- Multi-Vitamin Serum (₹849)\n"
                                         "- Lightweight Moisturizer (₹549)",
    "recommend product for combination skin": "Perfect balance:\n"
                                              "- pH-Balanced Gel Cleanser (₹449)\n"
                                              "- Multi-Vitamin Serum (₹849)\n"
                                              "- Lightweight Moisturizer (₹549)",
    "good product for combination skin": "Perfect balance:\n"
                                         "- pH-Balanced Gel Cleanser (₹449)\n"
                                         "- Multi-Vitamin Serum (₹849)\n"
                                         "- Lightweight Moisturizer (₹549)",
    "what is best for sensitive skin": "Gentle care:\n"
                                       "- Fragrance-Free Cream Cleanser (₹499)\n"
                                       "- Calming Serum (₹899)\n"
                                       "- Barrier Repair Cream (₹649)",
    "recommend product for sensitive skin": "Gentle care:\n"
                                            "- Fragrance-Free Cream Cleanser (₹499)\n"
                                            "- Calming Serum (₹899)\n"
                                            "- Barrier Repair Cream (₹649)",
    "good product for sensitive skin": "Gentle care:\n"
                                       "- Fragrance-Free Cream Cleanser (₹499)\n"
                                       "- Calming Serum (₹899)\n"
                                       "- Barrier Repair Cream (₹649)",
    "what is best for mature skin": "Age-defying:\n"
                                    "- Anti-Aging Cream Cleanser (₹599)\n"
                                    "- Retinol Night Serum (₹1199)\n"
                                    "- Firming Day Cream (₹899)",
    "recommend product for mature skin": "Age-defying:\n"
                                         "- Anti-Aging Cream Cleanser (₹599)\n"
                                         "- Retinol Night Serum (₹1199)\n"
                                         "- Firming Day Cream (₹899)",
    "good product for mature skin": "Age-defying:\n"
                                    "- Anti-Aging Cream Cleanser (₹599)\n"
                                    "- Retinol Night Serum (₹1199)\n"
                                    "- Firming Day Cream (₹899)",
    "what is best for normal skin": "Maintenance essentials:\n"
                                    "- Gentle Foam Cleanser (₹349)\n"
                                    "- Antioxidant Serum (₹749)\n"
                                    "- Hydrating Fluid (₹499)",
    "recommend product for normal skin": "Maintenance essentials:\n"
                                         "- Gentle Foam Cleanser (₹349)\n"
                                         "- Antioxidant Serum (₹749)\n"
                                         "- Hydrating Fluid (₹499)",
    "good product for normal skin": "Maintenance essentials:\n"
                                    "- Gentle Foam Cleanser (₹349)\n"
                                    "- Antioxidant Serum (₹749)\n"
                                    "- Hydrating Fluid (₹499)",
    "good skin care routine ": """Cleanse your face twice daily with a gentle, pH-balanced cleanser.
    Moisturize and apply sunscreen (SPF 30+) every morning, and use a hydrating serum or treatment at night. """,

    # ==== Pricing ====
    "price list": "Popular Products:\n"
                  "- Facewashes: ₹349-₹499\n"
                  "- Serums: ₹799-₹1299\n"
                  "- Sunscreens: ₹499-₹799\n"
                  "Full list at [Website Link]",

    # ==== Usage Guidance ====
    "how to use retinol": "Start 2 times a week at night → Moisturize after → Always use SPF in morning.",
    "can I use vitamin c with niacinamide": "Yes! They work well together for brightening and hydration.",

    # ==== Shipping/Returns ====
    "delivery time": "📦 Standard: 3-5 days | Express: 2 days (additional charges apply).",
    "return policy": "🔄 Unopened products: 30 days | Opened: 15 days (partial refund).",

    # ==== Safety/Ingredients ====
    "cruelty-free": "✅ All our products are Leaping Bunny certified cruelty-free!",
    "vegan products": "🌱 Vegan options:\n- Green Tea Toner\n- Aloe Moisturizer\n- Mineral Sunscreen",

    # ==== Customer Support ====
    "contact support": "Need any help \n Feel free to contact at  "
                       "📞 Call: 0313-7638717\n"
                       "📧 Email: care@beautybot.com\n"
                       "⏰ Hours: 10AM-7PM (Mon-Sat)"
}


# --- Routes ---
@app.route('/')
def home():
    logging.info(f"Request to home page from {request.remote_addr}")
    return render_template("index.html")


@app.route('/chat', methods=['POST'])
@limiter.limit("5 per minute")
def chat():
    # Initialize session history
    if 'history' not in session:
        session['history'] = []
        logging.info(f"Session history initialized for {request.remote_addr}.")

    user_input = request.json.get('message', '').strip()
    if not user_input:
        logging.warning(f"Empty message received from {request.remote_addr}.")
        return jsonify({"error": "Please enter a valid question."})

    user_input_lower = user_input.lower()
    logging.info(f"User {request.remote_addr} asked: '{user_input}'")

    bot_response = None  # Initialize bot_response to None

    # Handle cases where Gemini model might not be initialized
    if model is None:
        logging.error(f"Gemini model not initialized for {request.remote_addr}. Cannot process AI requests.")
        return jsonify({
            "response": "Sorry, the chatbot is currently experiencing technical difficulties. "
                        "Please try again later or contact support directly.",
            "suggestions": [
                "Ask about products",
                "Try 'order sunscreen'",
                "Track with 'where is order BEAUTY1234?'"
            ]
        }), 500

    # --- Order Tracking ---
    if any(keyword in user_input_lower for keyword in ["track", "where is", "status"]):
        order_id = None
        words = user_input.split()
        for word in words:
            if word.upper().startswith("BEAUTY") and word[6:].isdigit():
                order_id = word.upper()
                break
        if order_id in orders:
            update_order_status()
            order = orders[order_id]
            status_icons = {"Confirmed": "🟡", "Shipped": "🚚", "Delivered": "✅"}
            bot_response = (
                f"{status_icons.get(order['status'], '🟠')} Order #{order_id}\n"
                f"📦 Product: {order['product']}\n"
                f"🔄 Status: {order['status']}\n"
                f"📅 Delivery: {order['delivery_date']}"
            )
            if order["status"] == "Delivered":
                bot_response += "\n🎉 Your order has been delivered!"
            logging.info(f"[{request.remote_addr}] Processed order tracking for {order_id}. Status: {order['status']}")
        else:
            bot_response = f"❌ Order {order_id or '#'} not found. Please check your order ID."
            logging.warning(f"[{request.remote_addr}] Order tracking failed for ID: {order_id}. Not found.")

    # --- Order Placement ---
    elif any(keyword in user_input_lower for keyword in ["order", "buy", "purchase"]):
        product_found = False
        for key, product_data in PRODUCTS.items(): # Iterate with key and value
            # Check for full product name match or "1) Product Name" match
            if product_data["name"].lower() in user_input_lower or key.lower() in user_input_lower:
                product = key # Store the PRODUCTS dict key for easy lookup
                product_found = True
                break

        if product_found:
            if PRODUCTS[product]["stock"] <= 0:
                bot_response = f"❌ {PRODUCTS[product]['name']} is out of stock!"
                logging.warning(f"[{request.remote_addr}] Attempted to order out of stock product: {PRODUCTS[product]['name']}")
            else:
                order_id = generate_order_id()
                delivery_date = create_delivery_date()

                orders[order_id] = {
                    "product": PRODUCTS[product]["name"],
                    "price": PRODUCTS[product]["price"],
                    "status": "Confirmed",
                    "delivery_date": delivery_date,
                    "timestamp": datetime.now().isoformat()
                }
                PRODUCTS[product]["stock"] -= 1
                save_orders()

                bot_response = (
                    f"✅ Order #{order_id} Confirmed!\n"
                    f"📦 {PRODUCTS[product]['name']}\n"
                    f"💳 ₹{PRODUCTS[product]['price']}\n"
                    f"📅 Estimated Delivery: {delivery_date}\n"
                    f"🔗 Track with: 'Where is order {order_id}?'"
                )
                logging.info(f"[{request.remote_addr}] Order placed: #{order_id} for {PRODUCTS[product]['name']}")
        else:
            available = "\n".join([f"- {p} (₹{PRODUCTS[p]['price']})" for p in PRODUCTS.values()]) # Show names
            bot_response = (
                f"Sorry, I couldn't find the product in your request.\n"
                f"Available products:\n{available}\n"
                f"Say 'order [product name]' to place an order."
            )
            logging.warning(f"[{request.remote_addr}] Order placement failed. Product not found in input: '{user_input}'")

    # --- FAQ System ---
    elif "products" in user_input_lower or "what do you sell" in user_input_lower:
        available = "\n".join([f"- {v['name']} (₹{v['price']})" for v in PRODUCTS.values()]) # Show names and prices
        bot_response = f"Available products:\n{available}"
        logging.info(f"[{request.remote_addr}] Responded to 'products you sell' query.")

    elif any(user_input_lower == q.lower() for q in FAQS):  # Check for exact FAQ match
        original_key = next(q for q in FAQS if q.lower() == user_input_lower)
        bot_response = FAQS[original_key]
        logging.info(f"[{request.remote_addr}] Responded to exact FAQ: '{original_key}'")

    else:  # This 'else' block will catch everything that wasn't an order or exact FAQ match
        matches = get_close_matches(user_input_lower, [q.lower() for q in FAQS.keys()], n=1, cutoff=0.6)
        if matches:
            original_key = next(q for q in FAQS if q.lower() == matches[0])
            bot_response = FAQS[original_key]
            logging.info(f"[{request.remote_addr}] Responded to fuzzy FAQ match: '{original_key}'")
        else:
            # --- Gemini Fallback (ONLY REACHED IF NO OTHER CONDITIONS MET) ---
            if model: # Check if model was successfully initialized
                try:
                    # Construct chat history for Gemini
                    gemini_history = []
                    for entry in session['history'][-5:]: # Use last 5 turns for context
                        if "user" in entry and "bot" in entry:
                            gemini_history.append({"role": "user", "parts": [entry["user"]]})
                            gemini_history.append({"role": "model", "parts": [entry["bot"]]})

                    prompt = f"""You are BeautyBot, an e-commerce chatbot for a skincare store.
                    Your goal is to answer questions about skincare, recommend products, and assist with orders.
                    Keep responses concise, helpful, and under 3 sentences.
                    Do not provide information about products not listed in the provided PRODUCTS list.
                    Do not make up order IDs or product names.
                    Current products available: {list(PRODUCTS.keys())}.

                    User Query: {user_input}
                    """
                    # Start a new chat session with the history
                    chat_session = model.start_chat(history=gemini_history)

                    logging.info(f"[{request.remote_addr}] Attempting Gemini API call for user input: '{user_input}'")
                    logging.debug(f"[{request.remote_addr}] Prompt sent to Gemini: {prompt}")

                    response_obj = chat_session.send_message(prompt, request_options={"timeout": 60})

                    if response_obj and hasattr(response_obj, 'text') and response_obj.text:
                        bot_response = response_obj.text.strip()[:500] # Trim response to 500 chars
                        logging.info(f"[{request.remote_addr}] Gemini API call successful. Bot response: '{bot_response}'")
                    else:
                        bot_response = "I received an empty or unreadable response from the AI. Please try again."
                        logging.warning(
                            f"[{request.remote_addr}] Gemini API returned empty/unreadable response for input: '{user_input}'")

                except Exception as e:
                    logging.error(f"[{request.remote_addr}] Gemini API Error for input '{user_input}': {e}", exc_info=True)
                    bot_response = "Sorry, I am unable to connect to the AI at the moment. Please try again later."
            else:
                bot_response = "The AI model is not available. Please contact support if the problem persists."
                logging.error(f"[{request.remote_addr}] Gemini model not initialized, cannot serve AI fallback.")

    # Ensure bot_response is always a string
    if not isinstance(bot_response, str):
        # This handles cases where bot_response might be an error dict from the AI part
        # and converts it to a user-friendly string.
        if isinstance(bot_response, dict) and "error" in bot_response:
            bot_response = bot_response["error"] + ". " + " ".join(bot_response.get("suggestions", []))
        else:
            bot_response = "Sorry, I couldn't process that request."
            logging.error(f"[{request.remote_addr}] bot_response was not a string or expected dict: {bot_response}")


    # Log the final response before sending
    logging.info(f"[{request.remote_addr}] Final bot response: {bot_response[:100]}...") # Log first 100 chars

    # Append to session history (using consistent keys 'user' and 'bot')
    session['history'].append({"user": user_input, "bot": bot_response})
    session.modified = True # Important: tell Flask that session has been modified

    return jsonify({"response": bot_response})


# --- Run App ---
if __name__ == '__main__':
    port = int(os.environ.get("PORT", 5000))
    logging.info(f"Starting Flask app in debug mode on host 0.0.0.0, port {port} (for local development).")
    app.run(host='0.0.0.0', port=port, debug=True)