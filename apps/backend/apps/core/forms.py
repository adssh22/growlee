from django import forms

from apps.campaigns.models import Campaign, EntryPoint
from apps.merchants.models import Merchant
from apps.rewards.models import Reward


class MerchantForm(forms.ModelForm):
    class Meta:
        model = Merchant
        fields = ['name', 'logo', 'primary_color', 'accent_color', 'surface_color', 'text_color', 'heading_font', 'body_font']
        labels = {
            'name': 'Nom du commerce',
            'logo': 'Téléverser le logo',
            'primary_color': 'Couleur principale',
            'accent_color': 'Couleur accent',
            'surface_color': 'Couleur de fond parcours',
            'text_color': 'Couleur de texte parcours',
            'heading_font': 'Typo titres',
            'body_font': 'Typo textes',
        }
        widgets = {
            'logo': forms.ClearableFileInput(attrs={'accept': 'image/*'}),
            'primary_color': forms.TextInput(attrs={'type': 'color'}),
            'accent_color': forms.TextInput(attrs={'type': 'color'}),
            'surface_color': forms.TextInput(attrs={'type': 'color'}),
            'text_color': forms.TextInput(attrs={'type': 'color'}),
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
        fields = ['name', 'code', 'channel', 'placement']
        labels = {
            'name': 'Nom du point d’entrée',
            'code': 'Code interne QR / NFC',
            'channel': 'Type d’entrée',
            'placement': 'Emplacement',
        }


class RewardForm(forms.ModelForm):
    class Meta:
        model = Reward
        fields = ['name', 'reward_type', 'description', 'probability_weight', 'daily_quota', 'expires_in_hours', 'active']
