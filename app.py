from flask import Flask, render_template, request, redirect, session, url_for
import os
from werkzeug.utils import secure_filename
import psycopg2

app = Flask(__name__)
app.secret_key = "secret123"

UPLOAD_FOLDER = "static/uploads"
app.config["UPLOAD_FOLDER"] = UPLOAD_FOLDER

# ================= DB =================
def get_db():
    return psycopg2.connect(
        "postgresql://mirahr_user:k9uCFnx48TVqaLVsrOGvzPxXTsV57uLS@dpg-d7bm7hp17lss73amap80-a.singapore-postgres.render.com/mirahr"
    )

def init_db():
    conn = get_db()
    cur = conn.cursor()

    # DEPARTMENTS
    cur.execute("""
    CREATE TABLE IF NOT EXISTS departments (
        id SERIAL PRIMARY KEY,
        name VARCHAR(100)
    )
    """)
    
    # USERS
    cur.execute("""
    CREATE TABLE IF NOT EXISTS users (
        id SERIAL PRIMARY KEY,
        full_name VARCHAR(150),
        username VARCHAR(100),
        email VARCHAR(100),
        phone VARCHAR(50),
        ic_number VARCHAR(50),
        address TEXT,
        position VARCHAR(100),
        dept_id INT,
        role VARCHAR(20),
        password TEXT,
        enrollment_date DATE,
        entitlement INT DEFAULT 14,
        availability VARCHAR(50) DEFAULT 'Available'
    )
    """)

    # NOTICES
    cur.execute("""
    CREATE TABLE IF NOT EXISTS notices (
        id SERIAL PRIMARY KEY,
        content TEXT,
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
    )
    """)

    # AUTO ADD COLUMN IF NOT EXIST
    cur.execute("""
    ALTER TABLE notices 
    ADD COLUMN IF NOT EXISTS file VARCHAR(255)
    """)

    # POLICIES
    cur.execute("""
    CREATE TABLE IF NOT EXISTS policies (
        id SERIAL PRIMARY KEY,
        filename VARCHAR(255),
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
    )
    """)

    # LEAVES
    cur.execute("""
    CREATE TABLE IF NOT EXISTS leaves (
        id SERIAL PRIMARY KEY,
        user_id INT,
        leave_type VARCHAR(100),
        start_date DATE,
        end_date DATE,
        reason TEXT,
        status VARCHAR(20) DEFAULT 'Pending',
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
    )
    """)

    # CLAIMS
    cur.execute("""
    CREATE TABLE IF NOT EXISTS claims (
        id SERIAL PRIMARY KEY,
        user_id INT,
        title VARCHAR(255),
        amount DECIMAL,
        category VARCHAR(100),
        status VARCHAR(20) DEFAULT 'Pending',
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        receipt VARCHAR(255)
    )
    """)

    conn.commit()
    conn.close()

# ================= LOGIN =================
@app.route("/", methods=["GET","POST"])
def login():
    if request.method == "POST":
        email = request.form["email"]
        password = request.form["password"]

        if email == "admin@test.com" and password == "123":
            session["user_id"] = 1
            session["role"] = "admin"
            session["name"] = "Admin"
            return redirect("/admin/dashboard")

        elif email == "user@test.com" and password == "123":
            session["user_id"] = 2
            session["role"] = "user"
            session["name"] = "User"
            return redirect("/dashboard")

        else:
            return render_template("login.html", error="Invalid email or password")

    return render_template("login.html")

# ================= LOGOUT =================
@app.route("/logout")
def logout():
    session.clear()
    return redirect("/")

# ================= USER DASHBOARD =================
@app.route("/dashboard")
def dashboard():
    if "user_id" not in session:
        return redirect("/")

    conn = get_db()
    cur = conn.cursor()

    # CLAIM STATS
    cur.execute("SELECT COUNT(*) FROM claims WHERE user_id=%s", (session["user_id"],))
    total = cur.fetchone()[0]

    cur.execute("SELECT COUNT(*) FROM claims WHERE status='Pending' AND user_id=%s", (session["user_id"],))
    pending = cur.fetchone()[0]

    cur.execute("SELECT COUNT(*) FROM claims WHERE status='Approved' AND user_id=%s", (session["user_id"],))
    approved = cur.fetchone()[0]

    cur.execute("SELECT COUNT(*) FROM claims WHERE status='Rejected' AND user_id=%s", (session["user_id"],))
    rejected = cur.fetchone()[0]

    # CLAIM LIST (FIXED)
    cur.execute("""
        SELECT title, amount, category, status, created_at, receipt
        FROM claims
        WHERE user_id=%s
        ORDER BY created_at DESC
    """, (session["user_id"],))
    claims = cur.fetchall()

    # LEAVE LIST
    cur.execute("""
        SELECT leave_type, start_date, end_date, status
        FROM leaves
        WHERE user_id=%s
        ORDER BY created_at DESC
    """, (session["user_id"],))
    leaves = cur.fetchall()
    
    # NOTICE
    try:
        cur.execute("SELECT content, file FROM notices ORDER BY created_at DESC LIMIT 1")
    except:
        cur.execute("SELECT content FROM notices ORDER BY created_at DESC LIMIT 1")

    notice = cur.fetchone()

    # POLICY
    cur.execute("SELECT filename FROM policies ORDER BY created_at DESC LIMIT 1")
    policy = cur.fetchone()

    conn.close()

    return render_template("dashboard.html",
        total=total,
        pending=pending,
        approved=approved,
        rejected=rejected,
        claims=claims,
        leaves=leaves,
        notice=notice,
        policy=policy
    )

# ================= ADMIN DASHBOARD =================
@app.route("/admin/dashboard")
def admin_dashboard():
    if "user_id" not in session or session.get("role") != "admin":
        return redirect("/")

    conn = get_db()
    cur = conn.cursor()

    # CLAIM STATS
    cur.execute("""
    SELECT 
        COUNT(*),
        COUNT(*) FILTER (WHERE status='Pending'),
        COUNT(*) FILTER (WHERE status='Approved'),
        COUNT(*) FILTER (WHERE status='Rejected')
    FROM claims
    """)
    claim_stats = cur.fetchone()

    # LEAVE STATS
    cur.execute("""
    SELECT 
        COUNT(*),
        COUNT(*) FILTER (WHERE status='Pending'),
        COUNT(*) FILTER (WHERE status='Approved'),
        COUNT(*) FILTER (WHERE status='Rejected')
    FROM leaves
    """)
    leave_stats = cur.fetchone()
    
    # notice
    try:
        cur.execute("SELECT content, file FROM notices ORDER BY created_at DESC LIMIT 1")
    except:
        cur.execute("SELECT content FROM notices ORDER BY created_at DESC LIMIT 1")

    notice = cur.fetchone()
    
    # policy
    cur.execute("SELECT filename FROM policies ORDER BY created_at DESC LIMIT 1")
    policy = cur.fetchone()

    conn.close()

    return render_template("admin_dashboard.html",
        total_this_month=leave_stats[0],
        approved_leave=leave_stats[2],
        pending_leave=leave_stats[1],
        rejected_leave=leave_stats[3],
        claim_total=claim_stats[0],
        claim_pending=claim_stats[1],
        claim_approved=claim_stats[2],
        claim_rejected=claim_stats[3],
        recent_claims=[],
        recent_requests=[],
        on_leave_today=[],
        trend_labels=["Mon","Tue","Wed","Thu","Fri"],
        trend_data=[2,4,1,5,3],
        notice=notice,
        policy=policy
    )
    
# ================= ADMIN LEAVE DASHBOARD =================
@app.route("/admin/leaves/dashboard")
def admin_leave_dashboard():
    if session.get("role") != "admin":
        return redirect("/")

    conn = get_db()
    cur = conn.cursor()

    # stats
    cur.execute("""
    SELECT 
        COUNT(*),
        COUNT(*) FILTER (WHERE status='Pending'),
        COUNT(*) FILTER (WHERE status='Approved'),
        COUNT(*) FILTER (WHERE status='Rejected')
    FROM leaves
    """)
    stats = cur.fetchone()

    # list
    cur.execute("""
        SELECT l.id, u.name, l.leave_type, l.start_date, l.end_date, l.status
        FROM leaves l
        JOIN users u ON l.user_id = u.id
        ORDER BY l.created_at DESC
    """)
    leaves = cur.fetchall()

    conn.close()

    return render_template("admin_leave_dashboard.html",
        total=stats[0],
        pending=stats[1],
        approved=stats[2],
        rejected=stats[3],
        leaves=leaves
    )

# =========ADMIN CLAIM DASH=====================
@app.route("/admin/claims/dashboard")
def admin_claim_dashboard():
    if session.get("role") != "admin":
        return redirect("/")

    conn = get_db()
    cur = conn.cursor()

    # stats
    cur.execute("""
    SELECT 
        COUNT(*),
        COUNT(*) FILTER (WHERE status='Pending'),
        COUNT(*) FILTER (WHERE status='Approved'),
        COUNT(*) FILTER (WHERE status='Rejected')
    FROM claims
    """)
    stats = cur.fetchone()

    # list
    cur.execute("""
        SELECT c.id, u.name, c.title, c.amount, c.category, c.status
        FROM claims c
        JOIN users u ON c.user_id = u.id
        ORDER BY c.created_at DESC
    """)
    claims = cur.fetchall()

    conn.close()

    return render_template("admin_claim_dashboard.html",
        total=stats[0],
        pending=stats[1],
        approved=stats[2],
        rejected=stats[3],
        claims=claims
    )
    
# ======NOTICE DASHBOARD==S======
@app.route("/admin/notice", methods=["POST"])
def manage_notice():
    if session.get("role") != "admin":
        return redirect("/")

    content = request.form["content"]
    file = request.files.get("file")

    conn = get_db()
    cur = conn.cursor()

    filename = None

    if file and file.filename != "":
        filename = secure_filename(file.filename)
        file.save(os.path.join(app.config["UPLOAD_FOLDER"], filename))

    cur.execute("DELETE FROM notices")

    cur.execute("""
        INSERT INTO notices (content, file)
        VALUES (%s, %s)
    """, (content, filename))

    conn.commit()
    conn.close()

    return redirect("/admin/dashboard")

@app.route("/admin/policy", methods=["GET","POST"])
def upload_policy():
    if session.get("role") != "admin":
        return redirect("/")

    conn = get_db()
    cur = conn.cursor()

    if request.method == "POST":
        file = request.files.get("policy_file")

        if file:
            filename = secure_filename(file.filename)
            file.save(os.path.join(app.config["UPLOAD_FOLDER"], filename))

            cur.execute("DELETE FROM policies")
            cur.execute("INSERT INTO policies (filename) VALUES (%s)", (filename,))
            conn.commit()

    cur.execute("SELECT filename FROM policies ORDER BY created_at DESC LIMIT 1")
    policy = cur.fetchone()

    conn.close()

    return render_template("admin_policy.html", policy=policy)


# =================APPLY LEAVE===================
@app.route("/leave/apply", methods=["GET", "POST"])
def apply_leave():
    if "user_id" not in session:
        return redirect("/")

    if request.method == "POST":
        leave_type = request.form["leave_type"]
        start_date = request.form["start_date"]
        end_date = request.form["end_date"]
        reason = request.form["reason"]

        conn = get_db()
        cur = conn.cursor()

        cur.execute("""
            INSERT INTO leaves (user_id, leave_type, start_date, end_date, reason)
            VALUES (%s, %s, %s, %s, %s)
        """, (session["user_id"], leave_type, start_date, end_date, reason))

        conn.commit()
        conn.close()

        return redirect("/leave/my")

    return render_template("leaves/apply_leave.html")

# ==================VIEW LEAVES====================
@app.route("/leave/my")
def my_leave():
    if "user_id" not in session:
        return redirect("/")

    conn = get_db()
    cur = conn.cursor()

    cur.execute("""
        SELECT * FROM leaves WHERE user_id = %s ORDER BY created_at DESC
    """, (session["user_id"],))

    leaves = cur.fetchall()

    conn.close()

    return render_template("leaves/user_dashboard.html", leaves=leaves)

# =================ADMIN VIEW LEAVES==============
@app.route("/admin/leaves")
def admin_leaves():
    if session.get("role") != "admin":
        return redirect("/")

    conn = get_db()
    cur = conn.cursor()

    cur.execute("""
        SELECT l.*, u.name 
        FROM leaves l
        JOIN users u ON l.user_id = u.id
        ORDER BY l.created_at DESC
    """)

    leaves = cur.fetchall()

    conn.close()

    return render_template("leaves/adminLeave_dashboard.html", leaves=leaves)

# =============APPROVE/REJECT LEAVES=============
@app.route("/leave/update/<int:id>/<status>")
def update_leave(id, status):
    if session.get("role") != "admin":
        return redirect("/")

    conn = get_db()
    cur = conn.cursor()

    cur.execute("""
        UPDATE leaves SET status = %s WHERE id = %s
    """, (status, id))

    conn.commit()
    conn.close()

    return redirect("/admin/leaves")

# ================= SUBMIT CLAIM =================
@app.route("/claims/submit", methods=["GET","POST"])
def submit_claim():
    if "user_id" not in session:
        return redirect("/")

    if request.method == "POST":
        title = request.form["title"]
        amount = float(request.form["amount"])
        category = request.form["category"]

        file = request.files.get("receipt")
        filename = None

        if file:
            filename = secure_filename(file.filename)
            file.save(os.path.join(app.config["UPLOAD_FOLDER"], filename))

        conn = get_db()
        cur = conn.cursor()

        cur.execute("""
            INSERT INTO claims (user_id,title,amount,category,receipt)
            VALUES (%s,%s,%s,%s,%s)
        """, (session["user_id"], title, amount, category, filename))

        conn.commit()
        conn.close()

        return redirect("/dashboard")

    return render_template("claims/adminClaim/submit_claim.html")

# ================= ADMIN CLAIMS =================
@app.route("/admin/claims")
def admin_claims():
    if "role" not in session or session["role"] != "admin":
        return redirect("/")

    conn = get_db()
    cur = conn.cursor()

    cur.execute("""
        SELECT id, title, amount, category, status
        FROM claims
        ORDER BY created_at DESC
    """)

    claims = cur.fetchall()
    conn.close()

    return render_template("claims/adminClaim/claims_dashboard.html", claims=claims)

# ================= APPROVE =================
@app.route("/approve/<int:id>")
def approve(id):
    conn = get_db()
    cur = conn.cursor()

    cur.execute("UPDATE claims SET status='Approved' WHERE id=%s", (id,))
    conn.commit()
    conn.close()

    return redirect("/admin/claims")

# ================= REJECT =================
@app.route("/reject/<int:id>")
def reject(id):
    conn = get_db()
    cur = conn.cursor()

    cur.execute("UPDATE claims SET status='Rejected' WHERE id=%s", (id,))
    conn.commit()
    conn.close()

    return redirect("/admin/claims")

# ============= ADD USERS ================
@app.route("/admin/users/create", methods=["POST"])
def create_user():
    conn = get_db()
    cur = conn.cursor()

    cur.execute("""
        INSERT INTO users 
        (full_name, username, email, phone, ic_number, address, position,
         dept_id, role, password, enrollment_date, entitlement)
        VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
    """, (
        request.form["full_name"],
        request.form["username"],
        request.form["email"],
        request.form["phone"],
        request.form["ic_number"],
        request.form["address"],
        request.form["position"],
        request.form["dept_id"],
        request.form["role"],
        request.form["password"],
        request.form["enrollment_date"],
        request.form["entitlement"]
    ))

    conn.commit()
    conn.close()

    return redirect("/admin/users")

# ============ UPDATE USERS =============
@app.route("/admin/users/update/<int:id>", methods=["POST"])
def update_user(id):
    conn = get_db()
    cur = conn.cursor()

    cur.execute("""
        UPDATE users SET
        full_name=%s,
        email=%s,
        phone=%s,
        address=%s,
        position=%s,
        dept_id=%s,
        entitlement=%s,
        availability=%s
        WHERE id=%s
    """, (
        request.form["full_name"],
        request.form["email"],
        request.form["phone"],
        request.form["address"],
        request.form["position"],
        request.form["dept_id"],
        request.form["entitlement"],
        request.form["availability"],
        id
    ))

    conn.commit()
    conn.close()

    return "OK"

# ============ DELETE USERS =============
@app.route("/admin/users/delete/<int:id>", methods=["POST"])
def delete_user(id):
    conn = get_db()
    cur = conn.cursor()

    cur.execute("DELETE FROM users WHERE id=%s", (id,))

    conn.commit()
    conn.close()

    return "OK"

# ============ MANAGE DEPARTMENTS =============
@app.route("/admin/departments", methods=["POST"])
def manage_departments():
    conn = get_db()
    cur = conn.cursor()

    cur.execute("INSERT INTO departments (name) VALUES (%s)",
                (request.form["name"],))

    conn.commit()
    conn.close()

    return redirect("/admin/users")


@app.route("/admin/departments/delete/<int:dept_id>", methods=["POST"])
def delete_department(dept_id):
    conn = get_db()
    cur = conn.cursor()

    cur.execute("DELETE FROM departments WHERE id=%s", (dept_id,))

    conn.commit()
    conn.close()

    return redirect("/admin/users")
# ============== STAFF-USERS =============
@app.route("/admin/users")
def manage_users():
    if session.get("role") != "admin":
        return redirect("/")

    conn = get_db()
    cur = conn.cursor()

    # USERS WITH DEPARTMENT JOIN
    cur.execute("""
        SELECT 
            u.id,
            u.full_name,
            u.email,
            u.phone,
            u.address,
            u.position,
            u.entitlement,
            u.availability,
            u.dept_id,
            d.name as department_name
        FROM users u
        LEFT JOIN departments d ON u.dept_id = d.id
        ORDER BY u.id DESC
    """)

    columns = [desc[0] for desc in cur.description]
    users = [dict(zip(columns, row)) for row in cur.fetchall()]

    # DEPARTMENTS
    cur.execute("SELECT id, name FROM departments")
    departments = [dict(id=r[0], name=r[1]) for r in cur.fetchall()]

    conn.close()

    return render_template("admin_users.html",
                           users=users,
                           departments=departments)

# ================= RUN =================
if __name__ == "__main__":
    init_db()
    app.run(debug=True)
