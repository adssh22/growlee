from django import forms


class ClaimRewardForm(forms.Form):
    phone = forms.CharField(max_length=30, label='Téléphone')
    email = forms.EmailField(required=False, label='Email')
    first_name = forms.CharField(max_length=80, required=False, label='Prénom')
    consent = forms.BooleanField(required=False, initial=True, widget=forms.HiddenInput())
