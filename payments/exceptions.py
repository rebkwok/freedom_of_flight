

class PayPalProcessingError(Exception):
    pass


class StripeProcessingError(Exception):
    pass


class UnknownTransactionError(Exception):
    pass
