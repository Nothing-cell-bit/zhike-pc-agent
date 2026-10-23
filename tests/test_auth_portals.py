import pytest

from backend.db import Session, User
from backend.main import rate
from .conftest import post
from .test_workflow import guest

CUSTOMER = {'username': 'portal_customer', 'password': 'CustomerPortalPass123', 'display_name': '客户测试'}
STAFF = {'username': 'staff_test', 'password': 'StrongTestPassword!'}


def test_role_specific_logins_and_guest_history_are_preserved(clients):
    _, _, customer, other = clients
    cid = guest(customer)
    assert post(other, '/auth/register', CUSTOMER).status_code == 200
    assert post(customer, '/auth/staff/login', CUSTOMER).status_code == 403
    assert customer.get('/api/me').json()['user']['role'] == 'guest'
    assert customer.get('/api/conversations/' + cid).status_code == 200
    assert post(customer, '/auth/customer/login', STAFF).status_code == 403
    assert customer.get('/api/me').json()['user']['role'] == 'guest'
    signed_in = post(customer, '/auth/customer/login', CUSTOMER)
    assert signed_in.status_code == 200 and signed_in.json()['role'] == 'customer'
    assert customer.get('/api/conversations/' + cid).status_code == 200
    assert customer.get('/api/dashboard').status_code == 403
    assert post(other, '/auth/staff/login', STAFF).json()['role'] == 'staff'
    assert other.get('/api/dashboard').status_code == 200


@pytest.mark.parametrize('portal', ['customer', 'staff'])
def test_wrong_password_does_not_reveal_role_or_replace_existing_session(clients, portal):
    admin, _, customer, _ = clients
    guest(customer)
    before = customer.get('/api/me').json()['user']['id']
    response = post(customer, f'/auth/{portal}/login', {**STAFF, 'password': 'WrongPassword123'})
    assert response.status_code == 401 and response.json()['detail'] == '账号或密码不正确'
    assert customer.get('/api/me').json()['user']['id'] == before
    assert post(admin, '/auth/staff/login', {'username': 'admin_test', 'password': 'StrongTestPassword!'}).status_code == 200


def test_customer_registration_cannot_create_staff_and_only_admin_can_provision(clients):
    admin, staff, customer, anonymous = clients
    registered = post(customer, '/auth/register', {**CUSTOMER, 'role': 'admin', 'portal': 'staff'})
    assert registered.status_code == 200 and registered.json()['role'] == 'customer'
    new_staff = {'username': 'portal_worker', 'password': 'EmployeePortalPass123', 'display_name': '测试客服', 'role': 'staff'}
    assert post(anonymous, '/admin/users', new_staff).status_code == 401
    assert post(customer, '/admin/users', new_staff).status_code == 403
    assert post(staff, '/admin/users', new_staff).status_code == 403
    assert post(anonymous, '/auth/staff/register', new_staff).status_code in {404, 405}
    created = post(admin, '/admin/users', new_staff)
    assert created.status_code == 200 and created.json()['role'] == 'staff'
    assert post(anonymous, '/auth/staff/login', new_staff).status_code == 200
    with Session() as session:
        session.get(User, created.json()['id']).active = False
        session.commit()
    assert post(anonymous, '/auth/staff/login', new_staff).status_code == 401
    assert anonymous.get('/api/me').json()['user'] is None


def test_new_login_endpoints_keep_csrf_and_shared_rate_limit(clients):
    _, _, client, _ = clients
    for portal in ['customer', 'staff']:
        path = f'/api/auth/{portal}/login'
        assert client.post(path, json=STAFF).status_code == 403
        assert client.post(path, json=STAFF, headers={'X-Store-Request': '1', 'Origin': 'https://evil.example'}).status_code == 403
    rate.clear()
    for index in range(12):
        assert post(client, '/auth/'+('staff' if index % 2 else 'customer')+'/login',
                    {'username': 'nonexistent_user', 'password': 'WrongPassword123'}).status_code == 401
    assert post(client, '/auth/staff/login', STAFF).status_code == 429


def test_guest_identity_cannot_be_used_as_a_password_account(clients):
    client=clients[2]
    guest(client)
    username=client.get('/api/me').json()['user']['username']
    for portal in ['customer','staff']:
        assert post(client,f'/auth/{portal}/login',{'username':username,'password':'NotAnAccountPassword123'}).status_code==401
    assert client.get('/api/me').json()['user']['role']=='guest'
