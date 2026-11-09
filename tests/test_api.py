import io
import uuid
import pytest
from fastapi.testclient import TestClient
from backend.main import app, Base, engine

client = TestClient(app)

def test_full_pipeline():
    # 1. Register
    email = f"test_{uuid.uuid4().hex[:8]}@example.com"
    res = client.post('/api/auth/register', json={'name': 'Tester', 'email': email, 'password': 'password123'})
    assert res.status_code == 200

    # 2. Duplicate registration should return 409
    res = client.post('/api/auth/register', json={'name': 'Tester', 'email': email, 'password': 'password123'})
    assert res.status_code == 409

    # 3. Login
    res = client.post('/api/auth/login', json={'email': email, 'password': 'password123'})
    assert res.status_code == 200
    assert res.json()['email'] == email

    # 4. Check me
    res = client.get('/api/auth/me')
    assert res.status_code == 200
    assert res.json()['name'] == 'Tester'

    # 5. Upload CSV
    csv_content = b"Date,Amount,Category\n2026-01-01,100,Sales\n2026-01-02,200,Consulting\n2026-01-02,200,Consulting\n,,\n"
    res = client.post(
        '/api/datasets/upload',
        files={'file': ('test.csv', io.BytesIO(csv_content), 'text/csv')}
    )
    assert res.status_code == 200
    d_id = res.json()['id']

    # 6. Profile
    res = client.get(f'/api/datasets/{d_id}/profile')
    assert res.status_code == 200
    assert res.json()['rows'] == 4

    # 7. Preview cleaning
    res = client.post(
        f'/api/datasets/{d_id}/preview-cleaning',
        json={'drop_duplicates': True, 'missing': {'Category': 'drop'}, 'date_columns': ['Date']}
    )
    assert res.status_code == 200
    assert res.json()['after']['rows'] == 2

    # 8. Process cleaning
    res = client.post(
        f'/api/datasets/{d_id}/process',
        json={'drop_duplicates': True, 'missing': {'Category': 'drop'}, 'date_columns': ['Date']}
    )
    assert res.status_code == 200
    job_id = res.json()['job_id']

    # 9. Download
    res_csv = client.get(f'/api/jobs/{job_id}/download?format=csv')
    assert res_csv.status_code == 200
    assert b"Sales" in res_csv.content

    res_xlsx = client.get(f'/api/jobs/{job_id}/download?format=xlsx')
    assert res_xlsx.status_code == 200

    res_pdf = client.get(f'/api/jobs/{job_id}/download?format=pdf')
    assert res_pdf.status_code == 200
    assert res_pdf.content.startswith(b'%PDF')

    # 10. Analytics
    res_analytics = client.get(f'/api/datasets/{d_id}/analytics?amount_column=Amount&date_column=Date&category_column=Category')
    assert res_analytics.status_code == 200
    assert res_analytics.json()['total'] == 500.0
    assert res_analytics.json()['income'] == 500.0

    # 11. Download original raw dataset
    res_orig = client.get(f'/api/datasets/{d_id}/download')
    assert res_orig.status_code == 200
    assert b"Consulting" in res_orig.content

    # 12. Dashboard
    res_dash = client.get('/api/dashboard')
    assert res_dash.status_code == 200
    assert res_dash.json()['datasets'] >= 1

    # 13. Delete dataset
    res_del = client.delete(f'/api/datasets/{d_id}')
    assert res_del.status_code == 200
    assert res_del.json()['ok'] is True
