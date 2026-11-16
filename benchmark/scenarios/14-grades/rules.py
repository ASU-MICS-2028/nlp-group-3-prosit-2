"""Hidden tests for this scenario's business rules."""
USER = {"X-Role": "user", "X-User-Id": "1"}
OTHER = {"X-Role": "user", "X-User-Id": "2"}
ADMIN = {"X-Role": "admin", "X-User-Id": "9"}


def ok(r, code=201):
    assert r.status_code == code, f"{r.status_code} {r.text[:200]}"
    return r.json()


def student(client, number="S-001"):
    return ok(client.post("/students", json={"full_name": "Kojo Antwi", "student_number": number}, headers=ADMIN))["id"]


def subject(client, name="Mathematics"):
    return ok(client.post("/subjects", json={"name": name}, headers=ADMIN))["id"]


def grade(client, student_id, subject_id, score):
    return client.post("/grades", json={"student_id": student_id, "subject_id": subject_id, "score": score}, headers=ADMIN)


def average(client, student_id):
    r = client.get(f"/students/{student_id}/average", headers=USER)
    assert r.status_code == 200, r.text
    return r.json()


def test_score_must_be_between_0_and_100(client):
    s, m = student(client), subject(client)
    assert grade(client, s, m, -1).status_code == 422
    assert grade(client, s, m, 100.5).status_code == 422


def test_0_and_100_are_allowed(client):
    s = student(client)
    ok(grade(client, s, subject(client), 0))
    ok(grade(client, s, subject(client, "English"), 100))


def test_one_grade_per_student_per_subject(client):
    s, m = student(client), subject(client)
    ok(grade(client, s, m, 60))
    assert grade(client, s, m, 70).status_code == 409
    ok(grade(client, student(client, "S-002"), m, 70))    # another student, same subject
    ok(grade(client, s, subject(client, "English"), 70))  # same student, another subject


def test_correcting_a_score(client):
    g = ok(grade(client, student(client), subject(client), 60))
    assert ok(client.put(f"/grades/{g['id']}", json={"score": 65}, headers=ADMIN), 200)["score"] == 65
    assert client.put(f"/grades/{g['id']}", json={"score": 101}, headers=ADMIN).status_code == 422
    assert client.get("/grades", headers=ADMIN).json()[0]["score"] == 65


def test_average_with_no_grades(client):
    s = student(client)
    a = average(client, s)
    assert a["student_id"] == s and a["count"] == 0 and a["average"] is None


def test_average_is_the_mean_of_the_students_own_scores(client):
    s, other = student(client), student(client, "S-002")
    maths, english, science = subject(client), subject(client, "English"), subject(client, "Science")
    ok(grade(client, s, maths, 60)), ok(grade(client, s, english, 75)), ok(grade(client, s, science, 90))
    ok(grade(client, other, maths, 10))
    a = average(client, s)
    assert a["count"] == 3 and abs(a["average"] - 75.0) < 1e-6
    assert abs(average(client, other)["average"] - 10.0) < 1e-6


def test_average_follows_a_correction(client):
    s = student(client)
    g = ok(grade(client, s, subject(client), 60))
    client.put(f"/grades/{g['id']}", json={"score": 80}, headers=ADMIN)
    assert abs(average(client, s)["average"] - 80.0) < 1e-6


def test_average_of_an_unknown_student_is_404(client):
    assert client.get("/students/987654/average", headers=USER).status_code == 404


def test_average_needs_sign_in(client):
    assert client.get(f"/students/{student(client)}/average").status_code == 401
