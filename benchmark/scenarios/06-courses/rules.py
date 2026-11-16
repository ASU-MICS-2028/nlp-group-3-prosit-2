"""Hidden tests for this scenario's business rules."""
USER = {"X-Role": "user", "X-User-Id": "1"}
OTHER = {"X-Role": "user", "X-User-Id": "2"}
ADMIN = {"X-Role": "admin", "X-User-Id": "9"}


def ok(r, code=201):
    assert r.status_code == code, f"{r.status_code} {r.text[:200]}"
    return r.json()


def student(client, n=1):
    return ok(client.post("/students", json={"full_name": f"Student {n}", "email": f"s{n}@example.com"}))["id"]


def course(client, capacity=2, title="Bookkeeping"):
    return ok(client.post("/courses", json={"title": title, "capacity": capacity}, headers=ADMIN))["id"]


def enrol(client, student_id, course_id):
    return client.post("/enrolments", json={"student_id": student_id, "course_id": course_id}, headers=USER)


def test_capacity_must_be_at_least_one(client):
    assert client.post("/courses", json={"title": "Empty", "capacity": 0}, headers=ADMIN).status_code == 422
    c = course(client)
    assert client.put(f"/courses/{c}", json={"title": "Empty", "capacity": 0}, headers=ADMIN).status_code == 422


def test_enrolling_twice_in_the_same_course_is_409(client):
    s, c = student(client), course(client, 5)
    ok(enrol(client, s, c))
    assert enrol(client, s, c).status_code == 409


def test_a_student_can_take_two_different_courses(client):
    s = student(client)
    ok(enrol(client, s, course(client)))
    ok(enrol(client, s, course(client, title="Sewing")))


def test_a_full_course_is_409(client):
    c = course(client, 2)
    ok(enrol(client, student(client, 1), c))
    ok(enrol(client, student(client, 2), c))
    assert enrol(client, student(client, 3), c).status_code == 409
    assert len(client.get("/enrolments", headers=ADMIN).json()) == 2


def test_withdrawing_frees_the_place(client):
    c = course(client, 1)
    first = ok(enrol(client, student(client, 1), c))
    s2 = student(client, 2)
    assert enrol(client, s2, c).status_code == 409
    assert client.delete(f"/enrolments/{first['id']}", headers=USER).status_code == 204
    ok(enrol(client, s2, c))


def test_a_student_can_enrol_again_after_withdrawing(client):
    s, c = student(client), course(client)
    first = ok(enrol(client, s, c))
    client.delete(f"/enrolments/{first['id']}", headers=USER)
    ok(enrol(client, s, c))


def test_a_full_course_does_not_block_other_courses(client):
    full, other = course(client, 1), course(client, 1, "Sewing")
    ok(enrol(client, student(client, 1), full))
    ok(enrol(client, student(client, 2), other))
