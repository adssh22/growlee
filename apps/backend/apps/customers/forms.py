from django import forms


class ClaimRewardForm(forms.Form):
    phone = forms.CharField(max_length=30, label='Téléphone')
    email = forms.EmailField(required=False, label='Email')
    first_name = forms.CharField(max_length=80, required=False, label='Prénom')
    consent_marketing = forms.BooleanField(required=False, initial=False, label='Consentement marketing')
