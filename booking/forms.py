from django import forms


def get_available_users(user):
    return [(user.id, f"{user.first_name} {user.last_name}") for user in user.managed_users]


class AvailableUsersForm(forms.Form):

    def __init__(self, **kwargs):
        request = kwargs.pop("request")
        initial_view_as_user = kwargs.pop("view_as_user")
        super().__init__(**kwargs)
        self.fields["view_as_user"] = forms.CharField(
            max_length=255,
            widget=forms.Select(
                attrs={"class": "ml-2 form-control form-control-sm", "onchange": "form.submit()"},
                choices=get_available_users(request.user),
            ),
            initial=initial_view_as_user.id,
            label="Viewing as user"
        )