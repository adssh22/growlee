from django import forms
from django.contrib.auth.forms import UserCreationForm
from django.contrib.auth.models import User

from apps.campaigns.models import Campaign, EntryPoint
from apps.merchants.models import Merchant
from apps.rewards.models import Reward


class MerchantForm(forms.ModelForm):
    class Meta:
        model = Merchant
        fields = ['name', 'address', 'business_sector', 'tagline', 'short_bio', 'payment_method', 'logo', 'primary_color', 'accent_color', 'surface_color', 'text_color', 'heading_font', 'body_font', 'google_review_url', 'employee_pin']
        labels = {
            'name': 'Nom du commerce',
            'address': 'Adresse',
            'business_sector': 'Secteur d’activité',
            'tagline': 'Slogan',
            'short_bio': 'Petite biographie',
            'payment_method': 'Moyen de paiement',
            'logo': 'Téléverser le logo',
            'primary_color': 'Couleur principale',
            'accent_color': 'Couleur accent',
            'surface_color': 'Couleur de fond parcours',
            'text_color': 'Couleur de texte parcours',
            'heading_font': 'Typo titres',
            'body_font': 'Typo textes',
            'google_review_url': 'Lien Google de l’établissement',
            'employee_pin': 'PIN retour mode employeur',
        }
        help_texts = {
            'tagline': 'Facultatif. Exemple : “Le coffee shop qui donne le sourire.”',
            'short_bio': 'Facultatif. Quelques lignes pour personnaliser le ton du parcours client.',
            'payment_method': 'Exemple : CB, Stripe, virement, mandat, ou “à définir”.',
            'google_review_url': 'Exemple : lien Google Maps / Google Reviews de votre établissement.',
            'employee_pin': 'Utilisé pour quitter le mode employé sur tablette / caisse.',
        }
        widgets = {
            'short_bio': forms.Textarea(attrs={'rows': 4}),
            'logo': forms.ClearableFileInput(attrs={'accept': 'image/*'}),
            'primary_color': forms.TextInput(attrs={'type': 'color'}),
            'accent_color': forms.TextInput(attrs={'type': 'color'}),
            'surface_color': forms.TextInput(attrs={'type': 'color'}),
            'text_color': forms.TextInput(attrs={'type': 'color'}),
        }


class MerchantReviewForm(forms.ModelForm):
    class Meta:
        model = Merchant
        fields = ['google_review_url']
        labels = {
            'google_review_url': 'Lien Google de l’établissement',
        }
        help_texts = {
            'google_review_url': 'Collez ici le lien Google Maps / Google Reviews utilisé dans le parcours client.',
        }


class CampaignForm(forms.ModelForm):
    class Meta:
        model = Campaign
        fields = ['name', 'game_type', 'journey_type', 'reward_label', 'quiz_question', 'quiz_answer_a', 'quiz_answer_b', 'quiz_answer_c', 'scratch_label', 'landing_headline', 'landing_subheadline', 'cta_label', 'review_enabled', 'wallet_enabled', 'is_active']
        labels = {
            'name': 'Nom de la campagne',
            'game_type': 'Mini jeu',
            'journey_type': 'Type de parcours client',
            'reward_label': 'Promesse affichée',
            'quiz_question': 'Question du quiz',
            'quiz_answer_a': 'Réponse A',
            'quiz_answer_b': 'Réponse B',
            'quiz_answer_c': 'Réponse C',
            'scratch_label': 'Texte du ticket à gratter',
            'landing_headline': 'Titre écran d’accueil',
            'landing_subheadline': 'Sous-titre écran d’accueil',
            'cta_label': 'Texte du bouton principal',
            'review_enabled': 'Activer l’étape avis',
            'wallet_enabled': 'Activer l’étape wallet',
            'is_active': 'Campagne active',
        }


class EntryPointForm(forms.ModelForm):
    class Meta:
        model = EntryPoint
        fields = ['name', 'code', 'channel', 'placement', 'redirect_url']
        labels = {
            'name': 'Nom du point d’entrée',
            'code': 'Code interne QR / NFC',
            'channel': 'Type d’entrée',
            'placement': 'Emplacement',
            'redirect_url': 'Lien de redirection personnalisé',
        }
        help_texts = {
            'redirect_url': 'Laissez vide pour rediriger vers le parcours Growlee du commerce.',
        }


class RewardForm(forms.ModelForm):
    class Meta:
        model = Reward
        fields = ['name', 'reward_type', 'description', 'probability_weight', 'daily_quota', 'expires_in_hours', 'active']
        labels = {
            'name': 'Nom de la récompense',
            'reward_type': 'Type de récompense',
            'description': 'Description affichée au client',
            'probability_weight': 'Poids de probabilité',
            'daily_quota': 'Quota journalier',
            'expires_in_hours': 'Validité en heures',
            'active': 'Récompense active',
        }
        help_texts = {
            'probability_weight': 'Plus le poids est élevé, plus cette récompense a de chances de tomber.',
            'daily_quota': 'Nombre maximum distribué par jour.',
            'expires_in_hours': '168 h = 7 jours.',
        }
        widgets = {
            'description': forms.Textarea(attrs={'rows': 3}),
            'active': forms.CheckboxInput(attrs={'class': 'toggle-input'}),
        }


class MerchantSignupForm(UserCreationForm):
    business_name = forms.CharField(label='Nom du commerce', max_length=120)
    email = forms.EmailField(label='Email')

    class Meta(UserCreationForm.Meta):
        model = User
        fields = ('business_name', 'email', 'username', 'password1', 'password2')
        labels = {
            'username': 'Identifiant',
        }

    def clean_email(self):
        email = self.cleaned_data['email'].strip().lower()
        if User.objects.filter(email__iexact=email).exists():
            raise forms.ValidationError('Un compte existe déjà avec cet email.')
        return email

    def save(self, commit=True):
        user = super().save(commit=False)
        user.email = self.cleaned_data['email']
        if commit:
            user.save()
        return user


class StaffMerchantCreateForm(forms.Form):
    merchant_name = forms.CharField(label='Nom du commerce', max_length=120)
    owner_email = forms.EmailField(label='Email propriétaire')
    owner_username = forms.CharField(label='Identifiant propriétaire', max_length=150, required=False)
    owner_password = forms.CharField(label='Mot de passe temporaire', min_length=8, widget=forms.PasswordInput)
    is_active = forms.BooleanField(label='Commerce actif', required=False, initial=True)
    is_demo = forms.BooleanField(label='Accès démo apporteur d’affaires', required=False, initial=False)
    demo_days = forms.IntegerField(label='Durée démo (jours)', min_value=1, max_value=90, required=False, initial=14)

    def clean_owner_email(self):
        return self.cleaned_data['owner_email'].strip().lower()

    def clean_owner_username(self):
        username = (self.cleaned_data.get('owner_username') or '').strip()
        if username and User.objects.filter(username__iexact=username).exists():
            raise forms.ValidationError('Cet identifiant est déjà utilisé.')
        return username
