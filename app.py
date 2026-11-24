from flask import Flask, render_template, request, redirect, url_for, session, flash, Response
import sqlite3
from datetime import datetime, timedelta
from fpdf import FPDF

app = Flask(__name__)
app.secret_key = "super_secret_community_key" 

def init_db():
    conn = sqlite3.connect('ngo_database.db')
    cursor = conn.cursor()
    
    # TABLE 1: The Requests
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS wishlist (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            item_name TEXT,
            quantity INTEGER,
            status TEXT,
            ngo_id INTEGER,
            total_quantity INTEGER
        )
    ''')
    
    # TABLE 2: The Users
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS users (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            email TEXT UNIQUE,
            password TEXT,
            role TEXT
        )
    ''')
    
    # TABLE 3: The Donation Ledger
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS donations (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            donor_id INTEGER,
            ngo_id INTEGER,
            item_name TEXT,
            quantity INTEGER,
            date_time TEXT
        )
    ''')
    
    # Auto-create the Master NGO Account
    cursor.execute("SELECT * FROM users WHERE email='hemanth18gowdasb@gmail.com'")
    if not cursor.fetchone():
        cursor.execute("INSERT INTO users (email, password, role) VALUES (?, ?, ?)", 
                       ('hemanth18gowdasb@gmail.com', 'Hemanth@18', 'ngo'))
                       
    conn.commit()
    conn.close()

init_db()

@app.route("/")
def home():
    conn = sqlite3.connect('ngo_database.db')
    cursor = conn.cursor()
    cursor.execute("SELECT * FROM wishlist")
    all_items = cursor.fetchall()
    conn.close()
    return render_template("index.html", items=all_items)

# --- REGISTRATION ROUTE ---
@app.route("/register", methods=["GET", "POST"])
def register():
    if request.method == "POST":
        email = request.form.get("email")
        password = request.form.get("password")
        role = 'donor'
        
        conn = sqlite3.connect('ngo_database.db')
        cursor = conn.cursor()
        
        try:
            cursor.execute("INSERT INTO users (email, password, role) VALUES (?, ?, ?)", (email, password, role))
            conn.commit()
            conn.close()
            flash("Account created successfully! Please log in.", "success")
            return redirect(url_for('login_donor'))
                
        except sqlite3.IntegrityError:
            conn.close()
            flash("That email is already registered. Please try logging in or use another email.", "danger")
            return redirect(url_for('register'))
            
    return render_template("register.html")

# --- NGO ROUTES ---
@app.route("/login/ngo", methods=["GET", "POST"])
def login_ngo():
    if request.method == "POST":
        email = request.form.get("email")
        password = request.form.get("password")
        
        conn = sqlite3.connect('ngo_database.db')
        cursor = conn.cursor()
        cursor.execute("SELECT * FROM users WHERE email=? AND password=? AND role='ngo'", (email, password))
        user = cursor.fetchone()
        conn.close()
        
        if user:
            session['user_id'] = user[0]
            session['role'] = user[3]
            flash("Welcome back, Admin!", "success")
            return redirect(url_for('ngo_dashboard'))
        else:
            flash("Invalid NGO credentials. Please check your email and password.", "danger")
            return redirect(url_for('login_ngo'))
            
    return render_template("login_ngo.html")

@app.route("/dashboard/ngo")
def ngo_dashboard():
    if 'user_id' not in session or session.get('role') != 'ngo':
        return redirect(url_for('login_ngo'))
        
    conn = sqlite3.connect('ngo_database.db')
    cursor = conn.cursor()
    
    # 1. Fetch Live Requests
    cursor.execute("SELECT * FROM wishlist WHERE ngo_id=?", (session['user_id'],))
    ngo_items = cursor.fetchall()
    
    # 2. Fetch Donor Ledger with Timestamps
    cursor.execute('''
        SELECT users.email, donations.item_name, donations.quantity, donations.date_time
        FROM donations 
        JOIN users ON donations.donor_id = users.id 
        WHERE donations.ngo_id = ?
        ORDER BY donations.id DESC
    ''', (session['user_id'],))
    contributions = cursor.fetchall()
    
    # 3. Count Active (Pending) vs Fulfilled requests
    cursor.execute("SELECT COUNT(*) FROM wishlist WHERE ngo_id=? AND status='Pending'", (session['user_id'],))
    pending_count = cursor.fetchone()[0]
    
    cursor.execute("SELECT COUNT(*) FROM wishlist WHERE ngo_id=? AND status='Fulfilled'", (session['user_id'],))
    fulfilled_count = cursor.fetchone()[0]
    
    conn.close()
    
    return render_template(
        "dashboard_ngo.html", 
        items=ngo_items, 
        contributions=contributions,
        pending_count=pending_count,
        fulfilled_count=fulfilled_count
    )

@app.route("/add", methods=["POST"])
def add_item():
    if 'user_id' not in session or session.get('role') != 'ngo':
        return redirect(url_for('login_ngo'))
        
    name = request.form.get("item_name")
    qty = int(request.form.get("quantity"))
    ngo_id = session['user_id']
    
    conn = sqlite3.connect('ngo_database.db')
    cursor = conn.cursor()
    cursor.execute(
        "INSERT INTO wishlist (item_name, quantity, status, ngo_id, total_quantity) VALUES (?, ?, ?, ?, ?)", 
        (name, qty, 'Pending', ngo_id, qty)
    )
    conn.commit()
    conn.close()
    
    flash(f"Request for {qty} {name} posted successfully!", "success")
    return redirect(url_for('ngo_dashboard'))

# --- DELETE REQUEST ROUTE ---
@app.route("/delete/<int:item_id>", methods=["POST"])
def delete_item(item_id):
    if 'user_id' not in session or session.get('role') != 'ngo':
        return redirect(url_for('login_ngo'))
        
    conn = sqlite3.connect('ngo_database.db')
    cursor = conn.cursor()
    cursor.execute("DELETE FROM wishlist WHERE id = ? AND ngo_id = ?", (item_id, session['user_id']))
    conn.commit()
    conn.close()
    
    flash("Request deleted successfully.", "warning")
    return redirect(url_for('ngo_dashboard'))

# --- DOWNLOAD DONATION REPORT (PDF WITH TIME FILTER) ---
@app.route("/export/pdf")
def export_pdf():
    if 'user_id' not in session or session.get('role') != 'ngo':
        return redirect(url_for('login_ngo'))
        
    period = request.args.get("period", "all")
    now = datetime.now()
    
    period_config = {
        "week": (7, "Last 1 Week"),
        "month": (30, "Last 1 Month"),
        "year": (365, "Last 1 Year"),
        "all": (None, "All Time")
    }
    days, period_label = period_config.get(period, (None, "All Time"))
    cutoff_date = now - timedelta(days=days) if days else None
        
    conn = sqlite3.connect('ngo_database.db')
    cursor = conn.cursor()
    cursor.execute('''
        SELECT users.email, donations.item_name, donations.quantity, donations.date_time
        FROM donations 
        JOIN users ON donations.donor_id = users.id 
        WHERE donations.ngo_id = ?
        ORDER BY donations.id DESC
    ''', (session['user_id'],))
    all_rows = cursor.fetchall()
    conn.close()
    
    # Filter rows based on selected time range
    filtered_rows = []
    for row in all_rows:
        if cutoff_date is None:
            filtered_rows.append(row)
        else:
            try:
                row_date = datetime.strptime(row[3], "%d %b %Y, %I:%M %p")
                if row_date >= cutoff_date:
                    filtered_rows.append(row)
            except (ValueError, TypeError):
                continue

    # Build the PDF document
    pdf = FPDF()
    pdf.add_page()
    
    # Title Header
    pdf.set_font("Helvetica", "B", 18)
    pdf.set_text_color(13, 110, 253)
    pdf.cell(0, 12, "NGO Community Portal - Donation Report", ln=1, align="C")
    
    # Report Metadata
    pdf.set_font("Helvetica", "", 11)
    pdf.set_text_color(80, 80, 80)
    generated_str = now.strftime("%d %b %Y, %I:%M %p")
    pdf.cell(0, 8, f"Report Period: {period_label}   |   Generated On: {generated_str}", ln=1, align="C")
    pdf.ln(4)
    
    # Summary Box
    total_qty = sum(r[2] for r in filtered_rows)
    pdf.set_fill_color(240, 244, 255)
    pdf.set_text_color(0, 0, 0)
    pdf.set_font("Helvetica", "B", 11)
    pdf.cell(95, 10, f"  Total Donations Logged: {len(filtered_rows)}", border=1, fill=True)
    pdf.cell(95, 10, f"  Total Items Received: {total_qty}", border=1, fill=True, ln=1)
    pdf.ln(6)
    
    # Table Header
    pdf.set_fill_color(13, 110, 253)
    pdf.set_text_color(255, 255, 255)
    pdf.set_font("Helvetica", "B", 10)
    pdf.cell(65, 10, "Donor Email", border=1, fill=True, align="C")
    pdf.cell(55, 10, "Item Donated", border=1, fill=True, align="C")
    pdf.cell(25, 10, "Quantity", border=1, fill=True, align="C")
    pdf.cell(45, 10, "Date & Time", border=1, fill=True, align="C", ln=1)
    
    # Table Rows
    pdf.set_text_color(0, 0, 0)
    pdf.set_font("Helvetica", "", 10)
    
    if filtered_rows:
        for i, row in enumerate(filtered_rows):
            fill = (i % 2 == 1)
            pdf.set_fill_color(248, 249, 250)
            pdf.cell(65, 9, str(row[0])[:32], border=1, fill=fill)
            pdf.cell(55, 9, str(row[1])[:26], border=1, fill=fill)
            pdf.cell(25, 9, f"+{row[2]}", border=1, fill=fill, align="C")
            pdf.cell(45, 9, str(row[3] or ""), border=1, fill=fill, align="C", ln=1)
    else:
        pdf.cell(190, 12, f"No donations recorded for {period_label}.", border=1, align="C", ln=1)
        
    pdf_output = pdf.output()
    pdf_bytes = pdf_output.encode('latin-1') if isinstance(pdf_output, str) else bytes(pdf_output)
    
    filename = f"donation_report_{period}.pdf"
    return Response(
        pdf_bytes,
        mimetype="application/pdf",
        headers={"Content-Disposition": f"attachment;filename={filename}"}
    )

# --- DONOR ROUTES ---
@app.route("/login/donor", methods=["GET", "POST"])
def login_donor():
    if request.method == "POST":
        email = request.form.get("email")
        password = request.form.get("password")
        
        conn = sqlite3.connect('ngo_database.db')
        cursor = conn.cursor()
        cursor.execute("SELECT * FROM users WHERE email=? AND password=? AND role='donor'", (email, password))
        user = cursor.fetchone()
        conn.close()
        
        if user:
            session['user_id'] = user[0]
            session['role'] = user[3]
            flash("Logged in successfully! Ready to make an impact.", "success")
            return redirect(url_for('donor_dashboard'))
        else:
            flash("Invalid Donor credentials. Please try again.", "danger")
            return redirect(url_for('login_donor'))
            
    return render_template("login_donor.html")

@app.route("/dashboard/donor")
def donor_dashboard():
    if 'user_id' not in session or session.get('role') != 'donor':
        return redirect(url_for('login_donor'))
        
    conn = sqlite3.connect('ngo_database.db')
    cursor = conn.cursor()
    
    cursor.execute("SELECT * FROM wishlist WHERE status='Pending'")
    pending_items = cursor.fetchall()
    
    cursor.execute('''
        SELECT item_name, quantity, date_time 
        FROM donations 
        WHERE donor_id = ?
        ORDER BY id DESC
    ''', (session['user_id'],))
    my_donations = cursor.fetchall()
    
    conn.close()
    
    return render_template("dashboard_donor.html", items=pending_items, history=my_donations)

@app.route("/donate/<int:item_id>", methods=["POST"])
def donate_item(item_id):
    if 'user_id' not in session or session.get('role') != 'donor':
        return redirect(url_for('login_donor'))
        
    donated_qty = int(request.form.get("donated_qty"))
    donor_id = session['user_id']
    current_time = datetime.now().strftime("%d %b %Y, %I:%M %p")
        
    conn = sqlite3.connect('ngo_database.db')
    cursor = conn.cursor()
    
    cursor.execute("SELECT item_name, quantity, ngo_id FROM wishlist WHERE id = ?", (item_id,))
    item_data = cursor.fetchone()
    item_name = item_data[0]
    current_qty = item_data[1]
    ngo_id = item_data[2]
    
    cursor.execute(
        "INSERT INTO donations (donor_id, ngo_id, item_name, quantity, date_time) VALUES (?, ?, ?, ?, ?)",
        (donor_id, ngo_id, item_name, donated_qty, current_time)
    )
    
    new_qty = current_qty - donated_qty
    
    if new_qty > 0:
        cursor.execute("UPDATE wishlist SET quantity = ? WHERE id = ?", (new_qty, item_id))
    else:
        cursor.execute("UPDATE wishlist SET quantity = 0, status = 'Fulfilled' WHERE id = ?", (item_id,))
        
    conn.commit()
    conn.close()
    
    flash(f"Thank you! Your donation of {donated_qty} {item_name} has been recorded.", "success")
    return redirect(url_for('donor_dashboard'))

# --- LOGOUT ---
@app.route("/logout")
def logout():
    session.clear()
    flash("You have been logged out.", "info")
    return redirect(url_for('home'))

if __name__ == "__main__":
    app.run(debug=True)