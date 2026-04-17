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
    if session.get("role") != "admin":
        return redirect("/")

    conn = get_db()
    cur = conn.cursor()

    # ===== GET USERS (FULL DATA) =====
    cur.execute("""
        SELECT 
            u.id,
            u.full_name,
            u.email,
            u.phone,
            u.position,
            u.enrollment_date,
            d.name AS department
        FROM users u
        LEFT JOIN departments d ON u.dept_id = d.id
        ORDER BY u.id DESC
    """)

    rows = cur.fetchall()

    # convert to dict (IMPORTANT)
    users = []
    for r in rows:
        users.append({
            "id": r[0],
            "name": r[1],
            "email": r[2],
            "phone": r[3],
            "designation": r[4],
            "join_date": r[5],
            "department": r[6] or "-"
        })

    conn.close()

    return render_template("admin_dashboard.html", users=users)

# ================= EMPLOYEES =================
@app.route("/admin/users")
def admin_users():
    conn = get_db()
    cur = conn.cursor()

    cur.execute("""
        SELECT u.id, u.full_name, u.email, d.name
        FROM users u
        LEFT JOIN departments d ON u.dept_id = d.id
    """)

    users = cur.fetchall()

    cur.execute("SELECT id, name FROM departments")
    departments = cur.fetchall()

    conn.close()

    return render_template("manage_staff.html",
                           users=users,
                           departments=departments)


@app.route("/admin/users/create", methods=["POST"])
def create_user():
    conn = get_db()
    cur = conn.cursor()

    cur.execute("""
        INSERT INTO users (full_name, email, dept_id)
        VALUES (%s,%s,%s)
    """, (
        request.form["full_name"],
        request.form["email"],
        request.form["dept_id"]
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

    return "OK"


# ================= DEPARTMENTS =================
@app.route("/admin/departments", methods=["GET","POST"])
def manage_departments():
    conn = get_db()
    cur = conn.cursor()

    if request.method == "POST":
        cur.execute("INSERT INTO departments (name) VALUES (%s)",
                    (request.form["name"],))
        conn.commit()

    cur.execute("SELECT * FROM departments")
    departments = cur.fetchall()

    conn.close()

    return render_template("manage_department.html",
                           departments=departments)


# ================= LEAVES =================
@app.route("/admin/leaves")
def admin_leaves():
    conn = get_db()
    cur = conn.cursor()

    cur.execute("""
        SELECT l.id, u.full_name, l.leave_type, l.status
        FROM leaves l
        JOIN users u ON l.user_id = u.id
    """)

    leaves = cur.fetchall()
    conn.close()

    return render_template("leaves/admin_leave_dashboard.html",
                           leaves=leaves)


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


# ================= LOGOUT =================
@app.route("/logout")
def logout():
    session.clear()
    return redirect("/")


# ================= RUN =================
if __name__ == "__main__":
    app.run(debug=True)