from flask import Flask, request, render_template, redirect, url_for
import requests
from bs4 import BeautifulSoup, NavigableString, Comment
import re
import mysql.connector
from datetime import datetime

app = Flask(__name__)
app.secret_key = '1234'

db_config = {
    'host': 'localhost',
    'user': 'root',
    'password': 'mokshitha',
    'database': 'contactdb'
}

def decode_cfemail(cfemail):
    r = int(cfemail[:2], 16)
    email = ''.join(
        chr(int(cfemail[i:i+2], 16) ^ r)
        for i in range(2, len(cfemail), 2)
    )
    return email

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
        except Exception as e:
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
            r'\+91\s\d{5}\s\d{5}'
        )
        date_pattern = r'\b\d{1,2}-\d{1,2}-\d{4}\b'
        page_phones = set()
        for phone in re.findall(phone_pattern, page_text):
            if not re.fullmatch(date_pattern, phone):
                page_phones.add(phone)
        return page_emails, page_phones, page_soup

    # 1. Process main URL
    main_emails, main_phones, soup = process_page(url)
    emails.update(main_emails)
    phones.update(main_phones)
    visited.add(url)

    # 2. If either is empty, look for contact pages
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

    # Split phones into mobiles and landlines using 0 or 4 logic
    mobiles = set()
    landlines = set()
    for phone in phones:
        stripped = phone.strip()
        if stripped.startswith('+91'):
            rest = stripped[3:].lstrip('- ').lstrip()
            if rest.startswith(('0', '4')):
                landlines.add(phone)
            else:
                mobiles.add(phone)
        else:
            digits = re.sub(r'[^\d]', '', stripped)
            if digits.startswith(('0', '4')):
                landlines.add(phone)
            else:
                mobiles.add(phone)

    return list(emails), list(mobiles), list(landlines)

def store_or_update_contacts_in_mysql(emails, mobiles, landlines, website):
    conn = None
    try:
        conn = mysql.connector.connect(**db_config)
        cursor = conn.cursor()
        emails_str = ','.join(sorted(emails))
        mobiles_str = ','.join(sorted(mobiles))
        landlines_str = ','.join(sorted(landlines))
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

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=5000, debug=True)
