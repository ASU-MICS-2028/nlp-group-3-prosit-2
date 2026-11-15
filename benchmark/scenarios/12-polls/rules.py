"""Hidden tests for this scenario's business rules."""
USER = {"X-Role": "user", "X-User-Id": "1"}
OTHER = {"X-Role": "user", "X-User-Id": "2"}
ADMIN = {"X-Role": "admin", "X-User-Id": "9"}


def ok(r, code=201):
    assert r.status_code == code, f"{r.status_code} {r.text[:200]}"
    return r.json()


def poll(client, options=("Ada", "Aburi")):
    p = ok(client.post("/polls", json={"question": "Where do we hold the retreat?"}, headers=ADMIN))["id"]
    return p, [ok(client.post("/options", json={"poll_id": p, "label": label}, headers=ADMIN))["id"] for label in options]


def vote(client, option_id, headers=USER):
    return client.post("/votes", json={"option_id": option_id}, headers=headers)


def results(client, poll_id):
    r = client.get(f"/polls/{poll_id}/results")
    assert r.status_code == 200, r.text
    return {row["label"]: row["votes"] for row in r.json()}


def test_a_new_poll_is_open(client):
    p, _ = poll(client)
    assert client.get(f"/polls/{p}").json()["closed"] is False


def test_the_voter_comes_from_the_header(client):
    _, (a, _) = poll(client)
    assert ok(vote(client, a, USER))["user_id"] == 1
    assert ok(vote(client, a, OTHER))["user_id"] == 2


def test_one_vote_per_person_per_poll(client):
    _, (a, b) = poll(client)
    ok(vote(client, a))
    assert vote(client, a).status_code == 409    # the same option again
    assert vote(client, b).status_code == 409    # another option of the same poll
    assert len(client.get("/votes", headers=ADMIN).json()) == 1


def test_the_same_person_can_vote_in_another_poll(client):
    _, (a, _) = poll(client)
    _, (c, _) = poll(client, ("Yes", "No"))
    ok(vote(client, a))
    ok(vote(client, c))


def test_closing_a_poll(client):
    p, (a, _) = poll(client)
    assert ok(client.post(f"/polls/{p}/close", headers=ADMIN), 200)["closed"] is True
    assert vote(client, a).status_code == 409
    assert client.post("/polls/987654/close", headers=ADMIN).status_code == 404


def test_a_closed_poll_does_not_close_the_others(client):
    p, _ = poll(client)
    _, (c, _) = poll(client, ("Yes", "No"))
    client.post(f"/polls/{p}/close", headers=ADMIN)
    ok(vote(client, c))


def test_results_start_at_zero(client):
    p, _ = poll(client)
    assert results(client, p) == {"Ada": 0, "Aburi": 0}


def test_results_count_the_votes_of_this_poll_only(client):
    p, (a, b) = poll(client)
    q, (c, _) = poll(client, ("Yes", "No"))
    ok(vote(client, a, USER)), ok(vote(client, a, OTHER)), ok(vote(client, b, ADMIN))
    ok(vote(client, c, USER))
    assert results(client, p) == {"Ada": 2, "Aburi": 1}
    assert results(client, q) == {"Yes": 1, "No": 0}
    rows = client.get(f"/polls/{p}/results").json()
    assert sorted(row["option_id"] for row in rows) == sorted([a, b])


def test_results_of_an_unknown_poll_are_404(client):
    assert client.get("/polls/987654/results").status_code == 404
