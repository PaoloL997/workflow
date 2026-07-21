from django import forms
from django.contrib.auth.forms import PasswordResetForm


class WorkflowPasswordResetForm(PasswordResetForm):
    email = forms.EmailField(
        label="Email",
        max_length=254,
        widget=forms.EmailInput(
            attrs={
                "autocomplete": "email",
                "placeholder": "mario.rossi@brembanarolle.com",
            }
        ),
    )

    def clean_email(self):
        email = self.cleaned_data.get("email", "")
        if email and not email.lower().endswith("@brembanarolle.com"):
            raise forms.ValidationError(
                "È necessario usare un'email con dominio @brembanarolle.com."
            )
        return email
