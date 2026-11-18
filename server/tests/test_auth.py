from busvideo_server.security import hash_password, sign_session, verify_password, verify_session


def test_password_hash_roundtrip():
    h = hash_password("abc", iterations=1000)
    assert verify_password("abc", h) and not verify_password("abd", h)
    assert not verify_password("abc", "garbage")


def test_session_sign_verify():
    t = sign_session({"user": "a", "role": "admin"}, "s", 60)
    assert verify_session(t, "s")["user"] == "a"
    assert verify_session(t, "other") is None
    assert verify_session(sign_session({"u": 1}, "s", -10), "s") is None


def test_login_required_for_admin_routes(client):
    assert client.get("/api/devices").status_code == 401
    assert client.get("/api/video/latest").status_code == 401
    assert client.get("/", follow_redirects=False).status_code == 302


def test_login_flow(client, admin_password):
    r = client.post("/api/auth/login", json={"username": "admin", "password": "errada"})
    assert r.status_code == 401
    r = client.post("/api/auth/login", json={"username": "admin", "password": admin_password})
    assert r.status_code == 200 and "busvideo_session" in r.cookies
    assert client.get("/api/auth/me").json()["user"] == "admin"
    assert client.get("/", follow_redirects=False).status_code == 200
    client.post("/api/auth/logout")
    assert client.get("/api/auth/me").status_code == 401


def test_login_rate_limit(client, admin_password):
    for _ in range(5):
        client.post("/api/auth/login", json={"username": "admin", "password": "x"})
    r = client.post("/api/auth/login", json={"username": "admin", "password": admin_password})
    assert r.status_code == 429


def test_device_token(client, device_headers):
    assert client.get("/api/video/latest").status_code == 401
    assert client.get("/api/video/latest", headers={"Authorization": "Bearer wrong"}).status_code == 401
    assert client.get("/api/video/latest", headers=device_headers).status_code == 204
    assert client.get("/api/health").status_code == 200


def _login(client, user, pw):
    return client.post("/api/auth/login", json={"username": user, "password": pw}).status_code


def test_operator_login_and_role(operator):
    me = operator.get("/api/auth/me").json()
    assert me == {"user": "operador", "role": "operator"}
    assert operator.get("/api/devices").status_code == 200          # operador usa o painel normalmente
    assert operator.get("/api/auth/users").status_code == 403       # mas não vê as contas


def test_unknown_user_rejected(client, admin_password):
    assert _login(client, "ninguem", admin_password) == 401


def test_operator_cannot_change_other_users_password(operator, admin_password):
    r = operator.post("/api/auth/password", json={"username": "admin", "new_password": "nova-senha-123"})
    assert r.status_code == 403
    assert _login(operator, "admin", admin_password) == 200         # senha do admin intacta


def test_operator_changes_own_password_with_current(operator, operator_password):
    r = operator.post("/api/auth/password", json={"new_password": "nova-senha-123"})          # sem a atual
    assert r.status_code == 403
    r = operator.post("/api/auth/password", json={"current_password": "errada", "new_password": "nova-senha-123"})
    assert r.status_code == 403
    r = operator.post("/api/auth/password", json={"current_password": operator_password, "new_password": "curta"})
    assert r.status_code == 400
    r = operator.post("/api/auth/password", json={"current_password": operator_password, "new_password": "nova-senha-123"})
    assert r.status_code == 200
    operator.post("/api/auth/logout")
    assert _login(operator, "operador", operator_password) == 401
    assert _login(operator, "operador", "nova-senha-123") == 200


def test_admin_resets_forgotten_operator_password(admin, operator_password):
    users = admin.get("/api/auth/users").json()
    assert {u["user"]: u["role"] for u in users} == {"admin": "admin", "operador": "operator"}
    assert all(u["has_password"] for u in users) and not any("hash" in k for u in users for k in u)
    r = admin.post("/api/auth/password", json={"username": "operador", "new_password": "senha-recuperada"})
    assert r.status_code == 200                                     # sem precisar da senha atual
    assert admin.post("/api/auth/password", json={"username": "fantasma", "new_password": "senha-recuperada"}).status_code == 404
    admin.post("/api/auth/logout")
    assert _login(admin, "operador", operator_password) == 401
    assert _login(admin, "operador", "senha-recuperada") == 200


def test_admin_own_password_still_requires_current(admin, admin_password):
    r = admin.post("/api/auth/password", json={"username": "admin", "new_password": "outra-senha-123"})
    assert r.status_code == 403
    r = admin.post("/api/auth/password", json={"username": "admin", "current_password": admin_password,
                                               "new_password": "outra-senha-123"})
    assert r.status_code == 200


def test_db_password_survives_restart_and_env_only_seeds(settings, operator_password):
    """A senha trocada no painel vale depois de reiniciar, mesmo com o hash antigo ainda no server.env."""
    from fastapi.testclient import TestClient
    from busvideo_server.main import create_app
    from busvideo_server.security import hash_password
    with TestClient(create_app(settings)) as c:
        c.post("/api/auth/login", json={"username": "admin", "password": "senha-teste"})
        assert c.post("/api/auth/password", json={"username": "operador", "new_password": "trocada-no-painel"}).status_code == 200
    with TestClient(create_app(settings)) as c:                     # "reinício" com o mesmo server.env
        assert _login(c, "operador", operator_password) == 401
        assert _login(c, "operador", "trocada-no-painel") == 200
    # conta sem senha no banco + hash novo no env = semeia (caminho de instalação antiga que ganhou OPERATOR_*)
    settings.operator_user = "operador2"
    settings.operator_password_hash = ""
    with TestClient(create_app(settings)) as c:
        assert _login(c, "operador2", "qualquer-coisa") == 401
    settings.operator_password_hash = hash_password("semeada-depois", iterations=1000)
    with TestClient(create_app(settings)) as c:
        assert _login(c, "operador2", "semeada-depois") == 200


def test_set_password_cli(settings, monkeypatch, tmp_path):
    """Recuperação da senha do próprio administrador, no PC do servidor."""
    from fastapi.testclient import TestClient
    from busvideo_server import tools
    from busvideo_server.main import create_app
    with TestClient(create_app(settings)):
        pass
    monkeypatch.setattr("busvideo_server.config.load_settings", lambda: settings)
    monkeypatch.setattr(tools, "load_settings", lambda: settings, raising=False)
    import busvideo_server.config as cfg
    monkeypatch.setattr(cfg, "load_settings", lambda: settings)
    assert tools.main(["set-password", "admin", "senha-nova-admin"]) == 0
    assert tools.main(["set-password", "zeze", "senha-nova-admin"]) == 1
    assert tools.main(["set-password", "admin", "curta"]) == 1
    with TestClient(create_app(settings)) as c:
        assert _login(c, "admin", "senha-teste") == 401
        assert _login(c, "admin", "senha-nova-admin") == 200
