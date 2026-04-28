from django import forms
from django.contrib.auth import get_user_model


class RegistrazioneForm(forms.ModelForm):
    password = forms.CharField(
        label='Password',
        widget=forms.PasswordInput(attrs={'placeholder': 'Password'}),
    )
    first_name = forms.CharField(
        label='Nome',
        widget=forms.TextInput(attrs={'placeholder': 'Nome'}),
    )
    last_name = forms.CharField(
        label='Cognome',
        widget=forms.TextInput(attrs={'placeholder': 'Cognome'}),
    )

    class Meta:
        model = get_user_model()
        fields = ('username', 'first_name', 'last_name', 'email', 'password', 'ruolo')
        widgets = {
            'username': forms.TextInput(attrs={'placeholder': 'Username'}),
            'email': forms.EmailInput(attrs={'placeholder': 'Email'}),
            'ruolo': forms.TextInput(attrs={'placeholder': 'Ruolo (es. Project Manager)'}),
        }

    def save(self, commit=True):
        user = super().save(commit=False)
        user.set_password(self.cleaned_data['password'])
        if commit:
            user.save()
        return user
