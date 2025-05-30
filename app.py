from flask import Flask, request, render_template, redirect, url_for, session
import requests
from bs4 import BeautifulSoup
import re
import mysql.connector
from datetime import datetime

app = Flask(__name__)
app.secret_key = '1234'  # Replace with a secure random string

db_config = {
    'host': 'localhost',
    'user': 'root',
    'password': 'mokshitha',
    'database': 'contactdb'
}

def extract_contacts_from_url(url):
    try:
        headers = {
            "User-Agent": (
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/122.0.0.0 Safari/537.36"
            )
        }
        response = requests.get(url, headers=headers, timeout=10)
        response.raise_for_status()
    except Exception as e:
        print(f"Error fetching {url}: {e}")
        return [], []

    soup = BeautifulSoup(response.content, "html.parser")
    text = soup.get_text(separator=' ', strip=True)
    email_pattern = r'[a-zA-Z0-9_.%+-]+@[a-zA-Z0-9-]+\.[a-zA-Z0-9-.]+'

    phone_pattern = (
        r'\+91[-\s]?\d{10}'
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
    )

    date_pattern = r'\b\d{1,2}-\d{1,2}-\d{4}\b'

    emails = list(set(re.findall(email_pattern, text)))
    phones = list(set(re.findall(phone_pattern, text)))

    filtered_phones = [p for p in phones if not re.fullmatch(date_pattern, p)]

    return emails, filtered_phones

def store_or_update_contacts_in_mysql(emails, phones, website):
    conn = None
    try:
        conn = mysql.connector.connect(**db_config)
        cursor = conn.cursor()
        emails_str = ','.join(sorted(emails))
        phones_str = ','.join(sorted(phones))
        cursor.execute("SELECT emails, phones FROM contacts WHERE website = %s", (website,))
        result = cursor.fetchone()
        if result:
            old_emails, old_phones = result
            if old_emails != emails_str or old_phones != phones_str:
                cursor.execute("""
                    UPDATE contacts
                    SET emails = %s, phones = %s, date_uploaded = CURRENT_DATE
                    WHERE website = %s
                """, (emails_str, phones_str, website))
                conn.commit()
                return "Website already existed, but contacts were updated!"
            else:
                return "Website already exists in database with same contacts. No update needed."
        else:
            cursor.execute("""
                INSERT INTO contacts (website, emails, phones, date_uploaded)
                VALUES (%s, %s, %s, CURRENT_DATE)
            """, (website, emails_str, phones_str))
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
        cursor.execute("SELECT * FROM contacts ORDER BY sno ASC")
        contacts = cursor.fetchall()
        # Convert date_uploaded to datetime object if it's a string
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
    # Filter out deleted contacts stored in session
    deleted = set(session.get('deleted_contacts', []))
    contacts = [c for c in contacts if c['sno'] not in deleted]
    return contacts

@app.route('/', methods=['GET', 'POST'])
def index():
    message = ""
    if request.method == 'POST':
        url = request.form['url']
        emails, phones = extract_contacts_from_url(url)
        message = store_or_update_contacts_in_mysql(emails, phones, url)
    all_contacts = fetch_all_contacts()
    return render_template('index.html', all_contacts=all_contacts, message=message)

@app.route('/delete/<int:sno>', methods=['POST'])
def delete_contact(sno):
    deleted = set(session.get('deleted_contacts', []))
    deleted.add(sno)
    session['deleted_contacts'] = list(deleted)
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
            emails, phones = extract_contacts_from_url(website)
            store_or_update_contacts_in_mysql(emails, phones, website)
    except Exception as e:
        print("MySQL Error (refresh):", e)
    finally:
        if conn is not None and conn.is_connected():
            cursor.close()
            conn.close()
    return redirect(url_for('index'))

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=5000, debug=True)
