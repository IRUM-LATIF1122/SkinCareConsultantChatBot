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

# --- Setup ---
app = Flask(__name__)

# Configuration
load_dotenv()
app.secret_key = os.getenv("FLASK_SECRET_KEY", "fallback_secret_key")

# Logging
os.makedirs("logs", exist_ok=True)
logging.basicConfig(
    filename=f"logs/chatbot_{datetime.now().strftime('%Y%m%d')}.log",
    level=logging.INFO,
    format='%(asctime)s | %(levelname)s | %(message)s',
    datefmt='%Y-%m-%d %H:%M:%S'
)
logging.getLogger().setLevel(logging.DEBUG)  # Set to DEBUG for more detailed logging during development

# Rate limiting
limiter = Limiter(
    app=app,
    key_func=get_remote_address,
    storage_uri="memory://",
    default_limits=["200 per day", "50 per hour"]
)

# Gemini AI
load_dotenv()
genai.configure(api_key=os.getenv("GEMINI_API_KEY"))
model = genai.GenerativeModel("models/gemini-1.5-flash") # Or "models/gemini-pro"  # Or "models/gemini-1.5-flash" or "models/gemini-pro"

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

# Order storage with persistence
ORDERS_FILE = "orders.json"


def load_orders():
    try:
        with open(ORDERS_FILE) as f:
            return json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        return {}


def save_orders():
    with open(ORDERS_FILE, 'w') as f:
        json.dump(orders, f)


orders = load_orders()


# --- Helper Functions ---
def generate_order_id():
    return f"BEAUTY{random.randint(1000, 9999)}"


def create_delivery_date():
    return (datetime.now() + timedelta(days=3)).strftime("%d %b %Y")


def update_order_status():
    """Simulate status changes over time"""
    for order_id in orders:
        if orders[order_id]["status"] == "Confirmed":
            if random.random() > 0.7:  # 30% chance to advance status
                orders[order_id]["status"] = "Shipped"
        elif orders[order_id]["status"] == "Shipped":
            if random.random() > 0.8:  # 20% chance to deliver
                orders[order_id]["status"] = "Delivered"
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
    return render_template("index.html")


@app.route('/chat', methods=['POST'])
@limiter.limit("5 per minute")
def chat():
    # Initialize session history
    if 'history' not in session:
        session['history'] = []

    user_input = request.json.get('message', '').strip()
    if not user_input:
        return jsonify({"error": "Please enter a valid question."})

    user_input_lower = user_input.lower()
    logging.info(f"User {request.remote_addr} asked: '{user_input}'")

    bot_response = None  # Initialize bot_response to None

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
            bot_response = (  # Assign to bot_response instead of returning
                f"{status_icons.get(order['status'], '🟠')} Order #{order_id}\n"
                f"📦 Product: {order['product']}\n"
                f"🔄 Status: {order['status']}\n"
                f"📅 Delivery: {order['delivery_date']}"
            )
            if order["status"] == "Delivered":
                bot_response += "\n🎉 Your order has been delivered!"
        else:
            bot_response = f"❌ Order {order_id or '#'} not found. Please check your order ID."

    # --- Order Placement ---
    elif any(keyword in user_input_lower for keyword in ["order", "buy", "purchase"]):
        product = None
        for key in PRODUCTS:
            if key.lower() in user_input_lower or PRODUCTS[key]["name"].lower() in user_input_lower:
                product = key
                break

        if product:
            if PRODUCTS[product]["stock"] <= 0:
                bot_response = f"❌ {PRODUCTS[product]['name']} is out of stock!"
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

                bot_response = (  # Assign to bot_response instead of returning
                    f"✅ Order #{order_id} Confirmed!\n"
                    f"📦 {PRODUCTS[product]['name']}\n"
                    f"💳 ₹{PRODUCTS[product]['price']}\n"
                    f"📅 Estimated Delivery: {delivery_date}\n"
                    f"🔗 Track with: 'Where is order {order_id}?'"
                )
        else:
            available = "\n".join([f"- {p} (₹{PRODUCTS[p]['price']})" for p in PRODUCTS])
            bot_response = (  # Assign to bot_response instead of returning
                f"Sorry, I couldn't find the product in your request.\n"
                f"Available products:\n{available}\n"
                f"Say 'order [product name]' to place an order."
            )

    # --- FAQ System ---
    elif "products" in user_input_lower or "what do you sell" in user_input_lower:
        available = "\n".join([f"- {p} (₹{PRODUCTS[p]['price']})" for p in PRODUCTS])
        bot_response = f"Available products:\n{available}"  # Assign to bot_response

    elif any(user_input_lower == q.lower() for q in FAQS):  # Check for exact FAQ match
        original_key = next(q for q in FAQS if q.lower() == user_input_lower)
        bot_response = FAQS[original_key]  # Assign to bot_response

    else:  # This 'else' block will catch everything that wasn't an order or exact FAQ match
        matches = get_close_matches(user_input_lower, [q.lower() for q in FAQS.keys()], n=1, cutoff=0.6)
        if matches:
            original_key = next(q for q in FAQS if q.lower() == matches[0])
            bot_response = FAQS[original_key]  # Assign to bot_response
        else:
            # --- Gemini Fallback (ONLY REACHED IF NO OTHER CONDITIONS MET) ---
            try:
                prompt = f"""As BeautyBot (skincare + orders assistant), respond concisely:
                Context: {session['history'][-2:] or 'No context'}
                Query: {user_input}
                Available products: {list(PRODUCTS.keys())}
                Answer (max 3 sentences):"""

                logging.info(f"[{request.remote_addr}] Attempting Gemini API call for user input: '{user_input}'")
                logging.debug(f"[{request.remote_addr}] Prompt sent to Gemini: {prompt}")

                response_obj = model.generate_content(prompt,
                                                      request_options={"timeout": 60})  # Use a different var name

                # Check if the response actually contains text
                if response_obj and hasattr(response_obj, 'text') and response_obj.text:
                    bot_response = response_obj.text[:500]
                    logging.info(f"[{request.remote_addr}] Gemini API call successful. Bot response: '{bot_response}'")
                else:
                    bot_response = "I received an empty or unreadable response from the AI. Please try again."
                    logging.warning(
                        f"[{request.remote_addr}] Gemini API returned empty/unreadable response for input: '{user_input}'")

            except Exception as e:
                logging.error(f"[{request.remote_addr}] Gemini API Error for input '{user_input}': {e}", exc_info=True)
                bot_response = {  # Assign the error message to bot_response
                    "error": "Network error. Please check your connection.",
                    "suggestions": [
                        "Ask about products",
                        "Try 'order sunscreen'",
                        "Track with 'where is order BEAUTY1234?'"
                    ]
                }

    # Ensure bot_response is always a string or dict for jsonify
    if isinstance(bot_response, dict) and "error" in bot_response:
        pass  # Keep it as a dict if it's an error dict
    elif not isinstance(bot_response, str):
        # Fallback if bot_response somehow isn't set, though it should be by now
        bot_response = "Sorry, I couldn't process that request."

    # Log the final response before sending
    logging.info(f"[{request.remote_addr}] Final bot response: {bot_response}")

    session['history'].append({"user": user_input, "bot": bot_response})
    session.modified = True
    return jsonify({"response": bot_response})  # Single return at the end


if __name__ == '__main__':
    app.run(debug=True)