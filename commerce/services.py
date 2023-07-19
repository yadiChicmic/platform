import logging
import datetime
from django.db import transaction
from django.db.models import Sum

from talent.models import Person
from commerce.utils import CurrencyTypes, PaymentTypes
from .models import (
    Organisation,
    OrganisationAccount,
    OrganisationAccountCredit,
    OrganisationAccountCreditReasons,
    PointTypes,
    Cart,
    PointPriceConfiguration,
)


logger = logging.getLogger(__name__)


class OrganisationService:
    @transaction.atomic
    def create(self, username: str, name: str) -> Organisation:
        try:
            organisation = Organisation(username=username, name=name)
            organisation.save()
            return organisation
        except Exception as e:
            logger.error(f"Failed to create OrganisationPerson due to: {e}")
            return None

    @transaction.atomic
    def update(self, id: int, name: str) -> Organisation:
        try:
            organisation = Organisation.objects.get(pk=id)
            organisation.name = name
            organisation.save()
            return organisation
        except Organisation.DoesNotExist as e:
            logger.error(f"Failed to update Organisation due to: {e}")
            return None

    @transaction.atomic
    def delete(self, id: int) -> bool:
        try:
            organisation = Organisation.objects.get(pk=id)
            organisation.delete()
            return True
        except Organisation.DoesNotExist as e:
            logger.error(f"Failed to delete Organisation due to: {e}")
            return False


class OrganisationAccountService:
    @transaction.atomic
    def create(
        self,
        organisation: Organisation,
        liquid_points_balance: int,
        nonliquid_points_balance: int,
    ) -> OrganisationAccount:
        organisation_account = OrganisationAccount(
            organisation=organisation,
            liquid_points_balance=liquid_points_balance,
            nonliquid_points_balance=nonliquid_points_balance,
        )
        organisation_account.save()
        return organisation_account

    @transaction.atomic
    def update(
        self,
        id: int,
        organisation: Organisation,
        liquid_points_balance: int,
        nonliquid_points_balance: int,
    ):
        try:
            organisation_account = OrganisationAccount.objects.get(pk=id)
            organisation_account.organisation = organisation
            organisation_account.liquid_points_balance = liquid_points_balance
            organisation_account.nonliquid_points_balance = nonliquid_points_balance
            organisation_account.save()
            return organisation_account
        except OrganisationAccount.DoesNotExist as e:
            logger.error(f"Failed to update OrganisationAccount due to: {e}")

    @transaction.atomic
    def delete(self, id: int) -> bool:
        try:
            organisation_account = OrganisationAccount.objects.get(pk=id)
            organisation_account.delete()

            return True
        except OrganisationAccount.DoesNotExist as e:
            logger.error(f"Failed to delete OrganisationAccount due to: {e}")
            return False

    @staticmethod
    def credit(account: OrganisationAccount, granting_object: object) -> None:
        credit_reason = OrganisationAccountCreditReasons.GRANT
        type_of_points = PointTypes.NONLIQUID

        if (granting_object.__class__.__name__.lower()) == "salesorder":
            credit_reason = OrganisationAccountCreditReasons.SALE
            type_of_points = PointTypes.LIQUID

        # only grant points if granting_object has no existing related credit
        if not granting_object.organisation_account_credit:
            organisation_account_credit_service = OrganisationAccountCreditService()
            credit = organisation_account_credit_service.create(
                organisation_account=account,
                number_of_points=granting_object.number_of_points,
                credit_reason=credit_reason,
                type_of_points=type_of_points,
            )
            OrganisationAccountService._recalculate_balances(account)
            granting_object.mark_points_as_granted(credit)

    @staticmethod
    def _recalculate_balances(account: OrganisationAccount) -> None:
        nonliquid_credits = (
            OrganisationAccountCredit.objects.filter(
                organisation_account=account, type_of_points=PointTypes.NONLIQUID
            ).aggregate(Sum("number_of_points"))["number_of_points__sum"]
            or 0
        )
        nonliquid_debits = 0
        account.nonliquid_points_balance = nonliquid_credits - nonliquid_debits

        liquid_credits = (
            OrganisationAccountCredit.objects.filter(
                organisation_account=account, type_of_points=PointTypes.LIQUID
            ).aggregate(Sum("number_of_points"))["number_of_points__sum"]
            or 0
        )
        liquid_debits = 0
        account.liquid_points_balance = liquid_credits - liquid_debits

        account.save()


class OrganisationAccountCreditService:
    @transaction.atomic
    def create(
        self, organisation_account: OrganisationAccount, number_of_points: int
    ) -> OrganisationAccountCredit:
        org_acc_credit = OrganisationAccountCredit(
            organisation_account=organisation_account, number_of_points=number_of_points
        )
        org_acc_credit.save()
        return org_acc_credit

    @transaction.atomic
    def update(
        self,
        id: int,
        organisation_account: OrganisationAccount,
        number_of_points: int,
        type_of_points: PointTypes,
        credit_reason: OrganisationAccountCreditReasons,
    ) -> OrganisationAccountCredit:
        org_acc_credit = OrganisationAccountCredit.objects.get(pk=id)
        org_acc_credit.organisation_account = organisation_account
        org_acc_credit.number_of_points = number_of_points
        org_acc_credit.type_of_points = type_of_points
        org_acc_credit.credit_reason = credit_reason

    @transaction.atomic
    def delete(self, id: int) -> bool:
        try:
            org_acc_credit = OrganisationAccountCredit.objects.get(pk=id)
            org_acc_credit.delete()
        except OrganisationAccountCredit.DoesNotExist as e:
            logger.error(f"Failed to delete OrganisationAccountCredit due to: {e}")
            return False


class CartService:
    @transaction.atomic
    def create(
        self,
        organisation_account: OrganisationAccount,
        creator: Person,
        number_of_points: int,
        currency_of_payment: CurrencyTypes,
        payment_type: PaymentTypes,
    ) -> Cart:
        price_per_point_in_cents = self._get_point_inbound_price_in_cents(
            currency_of_payment
        )
        subtotal_in_cents = number_of_points * price_per_point_in_cents
        sales_tax_in_cents = 0  # TODO: create logic for sales tax based on org account
        total_payable_in_cents = subtotal_in_cents + sales_tax_in_cents

        cart = Cart(
            organisation_account=organisation_account,
            creator=creator,
            number_of_points=number_of_points,
            currency_of_payment=currency_of_payment,
            payment_type=payment_type,
            price_per_point_in_cents=price_per_point_in_cents,
            subtotal_in_cents=subtotal_in_cents,
            sales_tax_in_cents=sales_tax_in_cents,
            total_payable_in_cents=total_payable_in_cents,
        )

        return cart

    @transaction.atomic
    def delete(self, id: int) -> bool:
        try:
            cart = Cart.objects.get(pk=id)
            cart.delete()
            return True
        except Cart.DoesNotExist as e:
            logger.error(f"Failed to delete OrganisationAccountCredit due to: {e}")
            return False

    def _get_point_inbound_price_in_cents(self, currency: CurrencyTypes) -> int:
        conversion_rate_queryset = PointPriceConfiguration.objects.filter(
            applicable_from_date__lte=datetime.date.today()
        ).order_by("-created_at")
        conversion_rates = conversion_rate_queryset.first()

        if currency == CurrencyTypes.USD:
            return conversion_rates.usd_point_inbound_price_in_cents
        elif currency == CurrencyTypes.EUR:
            return conversion_rates.eur_point_inbound_price_in_cents
        elif currency == CurrencyTypes.GBP:
            return conversion_rates.gbp_point_inbound_price_in_cents
        else:
            raise ValueError("No conversion rate for given currency.", currency)
