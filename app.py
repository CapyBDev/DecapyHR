from flask import Flask, render_template, request, redirect, session, url_for
import os
from werkzeug.utils import secure_filename
import psycopg2

app = Flask(__name__)
app.secret_key = "secret123"

UPLOAD_FOLDER = "static/uploads"
app.config["UPLOAD_FOLDER"] = UPLOAD_FOLDER


# ================= DATABASE =================
def get_db():
    db_url = os.environ.get("DATABASE_URL")
    return psycopg2.connect(db_url, sslmode='require')


# ================= LOGIN =================
@app.route("/", methods=["GET","POST"])
def login():
    if request.method == "POST":
        email = request.form["email"]
        password = request.form["password"]

        if email == "admin@test.com":
            session["user_id"] = 1
            session["role"] = "admin"
            session["name"] = "Admin"
            return redirect("/admin/dashboard")

        elif email == "user@test.com":
            session["user_id"] = 2
            session["role"] = "user"
            session["name"] = "User"
            return redirect("/users")

    return render_template("login.html")


# ================= DASHBOARD =================
@app.route("/admin/dashboard")
def admin_dashboard():
    conn = get_db()
    cur = conn.cursor()

    cur.execute("SELECT COUNT(*) FROM users")
    total_employees = cur.fetchone()[0]

    cur.execute("SELECT COUNT(*) FROM departments")
    total_departments = cur.fetchone()[0]

    cur.execute("SELECT COUNT(*) FROM leaves WHERE status='Pending'")
    pending_leaves = cur.fetchone()[0]

    cur.execute("SELECT COUNT(*) FROM claims")
    total_claims = cur.fetchone()[0]
    
    # NEW EMPLOYEES (example: last 30 days)
    cur.execute("SELECT COUNT(*) FROM users")
    new_employees = cur.fetchone()[0]

    # SIMPLE HAPPINESS RATE (dummy logic)
    happiness_rate = 82

    # WORKING FORMAT (example static for now)
    work_format = [50, 20, 30]

    # PROJECT DATA
    project_data = [80,100,150,200,140,220,300]

    # ATTENDANCE DATA
    attendance_data = {
        "ontime": [30,20,15,25,28,35],
        "late": [20,15,10,20,18,25],
        "absent": [10,8,5,15,12,18]
    }

    # NOTICE
    cur.execute("SELECT content, file FROM notices ORDER BY created_at DESC LIMIT 1")
    notice = cur.fetchone()

    # CHART (example)
    trend_labels = ["Jan","Feb","Mar","Apr"]
    trend_data = [5,10,7,12]

    conn.close()

    return render_template("admin_dashboard.html",
        total_employees=total_employees,
        pending_leaves=pending_leaves,
        total_departments=total_departments,
        total_claims=total_claims,
        notice=notice,
        trend_labels=trend_labels,
        trend_data=trend_data,

        new_employees=new_employees,
        happiness_rate=happiness_rate,
        work_format=work_format,
        project_data=project_data,
        attendance_data=attendance_data
    )
# ================= EMPLOYEES =================
@app.route("/admin/users")
def admin_users():
    conn = get_db()
    cur = conn.cursor()

    #  FIXED QUERY (ALL REQUIRED FIELDS)
    cur.execute("""
        SELECT 
            u.id,
            u.full_name,
            u.email,
            u.phone,
            u.address,
            u.position,
            u.dept_id,
            u.entitlement,
            u.availability,
            d.name AS department_name
        FROM users u
        LEFT JOIN departments d ON u.dept_id = d.id
    """)

    #  CONVERT TO DICTIONARY (IMPORTANT FIX)
    columns = [col[0] for col in cur.description]
    users = [dict(zip(columns, row)) for row in cur.fetchall()]

    #  GET DEPARTMENTS
    cur.execute("SELECT id, name FROM departments")
    dept_columns = [col[0] for col in cur.description]
    departments = [dict(zip(dept_columns, row)) for row in cur.fetchall()]

    conn.close()

    return render_template("manage_staff.html",
                           users=users,
                           departments=departments)


@app.route("/admin/users/create", methods=["POST"])
def create_user():
    conn = get_db()
    cur = conn.cursor()

    cur.execute("""
        INSERT INTO users 
        (full_name, email, phone, address, position, dept_id, entitlement, availability)
        VALUES (%s,%s,%s,%s,%s,%s,%s,%s)
    """, (
        request.form["full_name"],
        request.form["email"],
        request.form.get("phone"),
        request.form.get("address"),
        request.form.get("position"),
        request.form.get("dept_id"),
        request.form.get("entitlement"),
        request.form.get("availability")
    ))

    conn.commit()
    conn.close()

    return redirect("/admin/users")

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
        request.form.get("phone"),
        request.form.get("address"),
        request.form.get("position"),
        request.form.get("dept_id"),
        request.form.get("entitlement"),
        request.form.get("availability"),
        id
    ))

    conn.commit()
    conn.close()

    return redirect("/admin/users")

@app.route("/admin/users/delete/<int:id>", methods=["POST"])
def delete_user(id):
    conn = get_db()
    cur = conn.cursor()

    cur.execute("DELETE FROM users WHERE id=%s", (id,))
    conn.commit()
    conn.close()

    return redirect("/admin/users")

# ================= DEPARTMENTS =================
@app.route("/admin/departments", methods=["GET", "POST"])
def manage_departments():
    conn = get_db()
    cur = conn.cursor()

    # ADD DEPARTMENT
    if request.method == "POST":
        cur.execute(
            "INSERT INTO departments (name) VALUES (%s)",
            (request.form["name"],)
        )
        conn.commit()

    # GET ALL DEPARTMENTS
    cur.execute("SELECT id, name FROM departments")

    columns = [col[0] for col in cur.description]
    departments = [dict(zip(columns, row)) for row in cur.fetchall()]

    conn.close()

    return render_template("manage_department.html",
                           departments=departments)

# ================= DELETE DEPARTMENT =================
@app.route("/admin/departments/delete/<int:dept_id>", methods=["POST"])
def delete_department(dept_id):
    conn = get_db()
    cur = conn.cursor()

    try:
        cur.execute("DELETE FROM departments WHERE id=%s", (dept_id,))
        conn.commit()
    except Exception as e:
        conn.rollback()
        return "Cannot delete department (might have employees assigned)"

    conn.close()

    return redirect("/admin/departments")

# ================= LEAVES =================
@app.route("/admin/leaves")
def admin_leaves():
    conn = get_db()
    cur = conn.cursor()

    cur.execute("""
        SELECT 
            l.id,
            u.full_name,
            l.leave_type,
            l.start_date,
            l.end_date,
            l.status
        FROM leaves l
        JOIN users u ON l.user_id = u.id
    """)

    leaves = cur.fetchall()

    # STATS
    cur.execute("SELECT COUNT(*) FROM leaves")
    total = cur.fetchone()[0]

    cur.execute("SELECT COUNT(*) FROM leaves WHERE status='Pending'")
    pending = cur.fetchone()[0]

    cur.execute("SELECT COUNT(*) FROM leaves WHERE status='Approved'")
    approved = cur.fetchone()[0]

    cur.execute("SELECT COUNT(*) FROM leaves WHERE status='Rejected'")
    rejected = cur.fetchone()[0]

    conn.close()

    return render_template(
        "leaves/admin_leave_dashboard.html",
        leaves=leaves,
        total=total,
        pending=pending,
        approved=approved,
        rejected=rejected
    )

@app.route("/leave/update/<int:id>/<status>")
def update_leave(id, status):
    conn = get_db()
    cur = conn.cursor()

    cur.execute("UPDATE leaves SET status=%s WHERE id=%s",
                (status, id))

    conn.commit()
    conn.close()

    return redirect("/admin/leaves")


# ================= CLAIMS =================
@app.route("/admin/claims")
def admin_claims():
    conn = get_db()
    cur = conn.cursor()

    cur.execute("""
        SELECT id, title, amount, status
        FROM claims
    """)

    claims = cur.fetchall()
    conn.close()

    return render_template("claims/claims_dashboard.html",
                           claims=claims)


@app.route("/claim/update/<int:id>/<status>")
def update_claim(id, status):
    conn = get_db()
    cur = conn.cursor()

    cur.execute("UPDATE claims SET status=%s WHERE id=%s",
                (status, id))

    conn.commit()
    conn.close()

    return redirect("/admin/claims")

@app.route("/admin/policy")
def policy():
    conn = get_db()
    cur = conn.cursor()

    cur.execute("""
        SELECT file FROM policies
        ORDER BY id DESC LIMIT 1
    """)

    result = cur.fetchone()
    policy_file = result[0] if result else None

    conn.close()

    return render_template("policy.html", policy_file=policy_file)

@app.route("/admin/policy/upload", methods=["POST"])
def upload_policy():
    file = request.files.get("file")

    if file and file.filename != "":
        filename = secure_filename(file.filename)
        file.save(os.path.join(app.config["UPLOAD_FOLDER"], filename))

        conn = get_db()
        cur = conn.cursor()

        cur.execute("""
            INSERT INTO policies (file)
            VALUES (%s)
        """, (filename,))

        conn.commit()
        conn.close()

    return redirect("/admin/policy")

# ================= NOTICE =================
@app.route("/admin/notice", methods=["POST"])
def update_notice():
    conn = get_db()
    cur = conn.cursor()

    content = request.form["content"]
    file = request.files.get("file")

    filename = None

    if file and file.filename != "":
        filename = secure_filename(file.filename)
        file.save(os.path.join(app.config["UPLOAD_FOLDER"], filename))

    cur.execute("""
        INSERT INTO notices (content, file)
        VALUES (%s, %s)
    """, (content, filename))

    conn.commit()
    conn.close()

    return redirect("/admin/dashboard")

# ================= LOGOUT =================
@app.route("/logout")
def logout():
    session.clear()
    return redirect("/")


# ================= RUN =================
if __name__ == "__main__":
    app.run(debug=True)