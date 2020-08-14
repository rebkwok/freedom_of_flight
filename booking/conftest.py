import pytest


@pytest.mark.django_db
@pytest.fixture
def student_user(django_user_model):
    student_user = django_user_model.objects.create_user(
        username='student@test.com', email='student@test.com', password='test',
        first_name="Student", last_name="User"
    )
    yield student_user
