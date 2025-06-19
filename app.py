from flask import Flask, request, render_template, redirect, url_for, jsonify, session
import requests
from bs4 import BeautifulSoup, NavigableString, Comment
import re
import mysql.connector
from datetime import datetime
import json

app = Flask(__name__)
app.secret_key = '1234'

db_config = {
    'host': 'localhost',
    'user': 'root',
    'password': 'mokshitha',
    'database': 'contactdb'
}

KNOWLARITY_SR_API_KEY = '7dee7087-b035-4557-9489-53b943dbfbcc'
KNOWLARITY_X_API_KEY = 'R3zHw7U5agaREaDVuzBeN6ke5vrY3QXda97pH2PJ'
KNOWLARITY_K_NUMBER = '+917353950600'
KNOWLARITY_AGENT_NUMBER = '+917093284780'
KNOWLARITY_CALLER_ID = '+918048160852'
KNOWLARITY_CHANNEL = 'Basic'

def is_valid_phone_number(number):
    digits = re.sub(r'\D', '', number)
    return len(digits) >= 10

@app.route('/login', methods=['GET', 'POST'])
def login():
    error = None
    if request.method == 'POST':
        agent_number = request.form.get('agent_number', '').strip()
        if not agent_number or not (agent_number.isdigit() or (agent_number.startswith('+') and agent_number[1:].isdigit())) or len(agent_number.replace('+', '')) < 10:
            error = "Please enter a valid agent number."
        else:
            session['agent_number'] = agent_number
            return redirect(url_for('index'))
    return render_template('login.html', error=error)

@app.route('/logout')
def logout():
    session.pop('agent_number', None)
    return redirect(url_for('login'))

def decode_cfemail(cfemail):
    r = int(cfemail[:2], 16)
    email = ''.join(
        chr(int(cfemail[i:i+2], 16) ^ r)
        for i in range(2, len(cfemail), 2)
    )
    return email

def classify_numbers(numbers):
    phones = set()
    landlines = set()
    for number in numbers:
        clean = re.sub(r'[^\d+]', '', number)
        if clean.startswith('0') and not clean.startswith('00'):
            clean = clean[1:]
        if clean.startswith('+91'):
            num = clean[3:]
        elif clean.startswith('91') and len(clean) > 10:
            num = clean[2:]
        else:
            num = clean
        if len(num) == 10 and num[0] in '6789':
            phones.add(number)
        else:
            landlines.add(number)
    return list(phones), list(landlines)

def extract_contacts_from_url(url):
    headers = {
        "User-Agent": (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 (KHTML, like Gecko) "
            "Chrome/122.0.0.0 Safari/537.36"
        )
    }
    emails = set()
    phones = set()
    visited = set()
    contact_keywords = ['contact', 'contact-us', 'contactus', 'contacts']

    def process_page(page_url):
        try:
            page_response = requests.get(page_url, headers=headers, timeout=15)
            page_response.raise_for_status()
        except Exception:
            return set(), set(), None
        page_soup = BeautifulSoup(page_response.content, "html.parser")
        page_text = page_soup.get_text(separator=' ', strip=True)
        email_pattern = r'[a-zA-Z0-9._%+-]+@[a-zA-Z0-9-]+\.[a-zA-Z]{2,}(?:\.[a-zA-Z]{2,})?'
        page_emails = set(re.findall(email_pattern, page_text))
        for span in page_soup.find_all("span", class_="__cf_email__"):
            cfemail = span.get("data-cfemail")
            if cfemail:
                page_emails.add(decode_cfemail(cfemail))
        for a_tag in page_soup.find_all('a', href=True):
            href = a_tag['href']
            if href.startswith('mailto:'):
                email = href[7:].split('?')[0]
                page_emails.add(email.strip())
        for span in page_soup.find_all("span", class_="elementor-icon-list-text"):
            parts = []
            for node in span.descendants:
                if isinstance(node, NavigableString) and not isinstance(node, Comment):
                    parts.append(str(node))
            email_candidate = ''.join(parts).replace(' ', '').replace('\n', '')
            match = re.search(email_pattern, email_candidate)
            if match:
                page_emails.add(match.group())
        phone_pattern = (
            r'\b\d{5}[-\s]\d{5}\b'
            r'|\b\d{4}\s\d{3}\s\d{3}\b'
            r'|\b0?40[-\s]?\d{8}\b'
            r'|\+91[-\s]?40[-\s]?\d{8}\b'
            r'|\b0?80[-\s]?\d{8}\b'
            r'|\+91[-\s]?80[-\s]?\d{8}\b'
            r'|\+91[-\s]?\d{10}'
            r'|\+91\s\d{2,4}\s\d{6,8}'
            r'|\b0\d{9,10}\b'
            r'|\b\d{10}\b'
            r'|\b\d{3,4}\s\d{3,4}\s\d{3,4}\b'
            r'|\+91(?:-\d{2,5}){1,5}(?:/\d{1,4})?'
            r'|\b(?:\d{2,5}-){2,}\d{2,5}(?:/\d{1,4})?\b'
            r'|\b1\d{3}[\s-]?\d{3}[\s-]?\d{4}\b'
            r'|\b0?\d{2,4}-\d{6,8}\b'
            r'|\+91[\s-]?\d{2,4}[\s-]?\d{4}[\s-]?\d{4}'
            r'|\b\d{3,4}-\d{5,8}(?:/\d{2,8})+\b'
            r'|\+91[\s-]*\d{2,4}[\s-]*\d{5,8}(?:/\d{2,8})+\b'
            r'|\b\d{3,4}[-\s]\d{6,8}\b'
            r'\+91\s\d{5}\s\d{5}'
        )
        date_pattern = r'\b\d{1,2}-\d{1,2}-\d{4}\b'
        page_phones = set()
        for phone in re.findall(phone_pattern, page_text):
            if not re.fullmatch(date_pattern, phone):
                if is_valid_phone_number(phone):
                    page_phones.add(phone)
        return page_emails, page_phones, page_soup

    main_emails, main_phones, soup = process_page(url)
    emails.update(main_emails)
    phones.update(main_phones)
    visited.add(url)
    if (not emails or not phones) and soup:
        contact_links = set()
        for a in soup.find_all('a', href=True):
            href = a['href'].lower()
            if any(kw in href for kw in contact_keywords):
                full_url = requests.compat.urljoin(url, a['href'])
                if full_url not in visited:
                    contact_links.add(full_url)
                    visited.add(full_url)
        for contact_url in contact_links:
            c_emails, c_phones, _ = process_page(contact_url)
            emails.update(c_emails)
            phones.update(c_phones)

    mobiles, landlines = classify_numbers(phones)
    mobiles = list(dict.fromkeys(mobiles))
    landlines = list(dict.fromkeys(landlines))
    emails = list(dict.fromkeys(emails))
    return emails, mobiles, landlines

def store_or_update_contacts_in_mysql(emails, mobiles, landlines, website):
    conn = None
    try:
        conn = mysql.connector.connect(**db_config)
        cursor = conn.cursor()
        emails_str = ','.join(sorted(emails))
        mobiles_str = ','.join(sorted(mobiles))
        landlines_str = ','.join(sorted(landlines))

        cursor.execute("""
            SELECT sno FROM contacts
            WHERE emails = %s AND mobiles = %s AND landlines = %s AND deleted = FALSE
        """, (emails_str, mobiles_str, landlines_str))
        duplicate = cursor.fetchone()
        if duplicate:
            return "These contacts already exist in the database. No new record added."

        cursor.execute("SELECT emails, mobiles, landlines FROM contacts WHERE website = %s AND deleted = FALSE", (website,))
        result = cursor.fetchone()
        if result:
            old_emails, old_mobiles, old_landlines = result
            if old_emails != emails_str or old_mobiles != mobiles_str or old_landlines != landlines_str:
                cursor.execute("""
                    UPDATE contacts
                    SET emails = %s, mobiles = %s, landlines = %s, date_uploaded = CURRENT_DATE
                    WHERE website = %s
                """, (emails_str, mobiles_str, landlines_str, website))
                conn.commit()
                return "Website already existed, but contacts were updated!"
            else:
                return "Website already exists in database with same contacts. No update needed."
        else:
            cursor.execute("""
                INSERT INTO contacts (website, emails, mobiles, landlines, date_uploaded, deleted)
                VALUES (%s, %s, %s, %s, CURRENT_DATE, FALSE)
            """, (website, emails_str, mobiles_str, landlines_str))
            conn.commit()
            return "Website and contacts added successfully!"
    except Exception as e:
        print("MySQL Error:", e)
        return "Database error occurred."
    finally:
        if conn is not None and conn.is_connected():
            cursor.close()
            conn.close()

def fetch_all_contacts():
    contacts = []
    conn = None
    try:
        conn = mysql.connector.connect(**db_config)
        cursor = conn.cursor(dictionary=True)
        cursor.execute("SELECT * FROM contacts WHERE deleted = FALSE ORDER BY sno ASC")
        contacts = cursor.fetchall()
        for row in contacts:
            if isinstance(row['date_uploaded'], str):
                try:
                    row['date_uploaded'] = datetime.strptime(row['date_uploaded'], "%Y-%m-%d")
                except Exception:
                    pass
    except Exception as e:
        print("MySQL Error:", e)
    finally:
        if conn is not None and conn.is_connected():
            cursor.close()
            conn.close()
    return contacts

@app.route('/', methods=['GET', 'POST'])
def index():
    if 'agent_number' not in session:
        return redirect(url_for('login'))
    message = ""
    if request.method == 'POST':
        url = request.form['url']
        emails, mobiles, landlines = extract_contacts_from_url(url)
        message = store_or_update_contacts_in_mysql(emails, mobiles, landlines, url)
    all_contacts = fetch_all_contacts()
    return render_template('index.html', all_contacts=all_contacts, message=message)

@app.route('/delete/<int:sno>', methods=['POST'])
def delete_contact(sno):
    conn = None
    try:
        conn = mysql.connector.connect(**db_config)
        cursor = conn.cursor()
        cursor.execute("UPDATE contacts SET deleted = TRUE WHERE sno = %s", (sno,))
        conn.commit()
    except Exception as e:
        print("MySQL Error (delete):", e)
    finally:
        if conn is not None and conn.is_connected():
            cursor.close()
            conn.close()
    return redirect(url_for('index'))

@app.route('/refresh/<int:sno>', methods=['POST'])
def refresh_contact(sno):
    conn = None
    try:
        conn = mysql.connector.connect(**db_config)
        cursor = conn.cursor()
        cursor.execute("SELECT website FROM contacts WHERE sno = %s", (sno,))
        result = cursor.fetchone()
        if result:
            website = result[0]
            emails, mobiles, landlines = extract_contacts_from_url(website)
            store_or_update_contacts_in_mysql(emails, mobiles, landlines, website)
    except Exception as e:
        print("MySQL Error (refresh):", e)
    finally:
        if conn is not None and conn.is_connected():
            cursor.close()
            conn.close()
    return redirect(url_for('index'))

@app.route('/click2call', methods=['POST'])
def click2call():
    if 'agent_number' not in session:
        return jsonify({"success": False, "message": "You must log in with your agent number."}), 401
    customer_number = request.json.get('number')
    agent_number = session['agent_number']
    if not customer_number:
        return jsonify({"success": False, "message": "Customer number is required"})
    customer_number = customer_number.replace(' ', '')
    if not customer_number.startswith('+91'):
        customer_number = '+91' + customer_number
    api_url = f"https://kpi.knowlarity.com/{KNOWLARITY_CHANNEL}/v1/account/call/makecall"
    headers = {
        'Content-Type': 'application/json',
        'authorization': KNOWLARITY_SR_API_KEY,
        'x-api-key': KNOWLARITY_X_API_KEY,
        'channel': KNOWLARITY_CHANNEL,
        'cache-control': 'no-cache'
    }
    payload = {
        "k_number": KNOWLARITY_K_NUMBER,
        "agent_number": agent_number,
        "customer_number": customer_number,
        "caller_id": KNOWLARITY_CALLER_ID
    }
    try:
        response = requests.post(api_url, json=payload, headers=headers, timeout=30)
        if response.status_code == 200:
            try:
                data = response.json()
                return jsonify({"success": True, "message": "Call initiated successfully!", "data": data})
            except json.JSONDecodeError:
                return jsonify({"success": True, "message": "Call initiated successfully!", "data": {"raw_response": response.text}})
        else:
            try:
                error_data = response.json()
            except json.JSONDecodeError:
                error_data = {"raw_response": response.text}
            return jsonify({"success": False, "message": f"API returned status code: {response.status_code}", "error_details": error_data})
    except requests.exceptions.Timeout:
        return jsonify({"success": False, "message": "Request timeout - API took too long to respond"})
    except requests.exceptions.ConnectionError:
        return jsonify({"success": False, "message": "Connection error - Unable to reach Knowlarity API"})
    except requests.exceptions.RequestException as e:
        return jsonify({"success": False, "message": f"Network error: {str(e)}"})
    except Exception as e:
        return jsonify({"success": False, "message": f"Unexpected error: {str(e)}"})

@app.route('/log_activity', methods=['POST'])
def log_activity():
    if 'agent_number' not in session:
        return jsonify({'success': False, 'message': 'Not logged in'}), 401
    data = request.json
    contact_type = data.get('contact_type')
    contact_value = data.get('contact_value')
    agent_number = session['agent_number']
    clicked_at = datetime.now()
    try:
        conn = mysql.connector.connect(**db_config)
        cursor = conn.cursor()
        cursor.execute("""
            INSERT INTO call_activity (agent_number, contact_type, contact_value, clicked_at)
            VALUES (%s, %s, %s, %s)
        """, (agent_number, contact_type, contact_value, clicked_at))
        conn.commit()
        cursor.close()
        conn.close()
        return jsonify({'success': True})
    except Exception as e:
        return jsonify({'success': False, 'message': str(e)}), 500

@app.route('/activity')
def activity():
    if 'agent_number' not in session:
        return redirect(url_for('login'))
    conn = mysql.connector.connect(**db_config)
    cursor = conn.cursor(dictionary=True)
    cursor.execute("""
        SELECT agent_number, contact_type, contact_value, clicked_at
        FROM call_activity
        ORDER BY clicked_at DESC
    """)
    activities = cursor.fetchall()
    cursor.close()
    conn.close()
    return render_template('activity.html', activities=activities)

@app.errorhandler(404)
def not_found(error):
    return jsonify({"error": "Endpoint not found"}), 404

@app.errorhandler(500)
def internal_error(error):
    return jsonify({"error": "Internal server error"}), 500

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=5000, debug=True)
