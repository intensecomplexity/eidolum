"""Mapping of institutional analyst firm names to their website URLs."""

FIRM_URLS = {
    "Goldman Sachs": "https://www.goldmansachs.com",
    "JPMorgan": "https://www.jpmorgan.com",
    "Morgan Stanley": "https://www.morganstanley.com",
    "Bank of America": "https://www.bankofamerica.com",
    "Citi Research": "https://www.citigroup.com",
    "Citi": "https://www.citigroup.com",
    "Barclays": "https://www.barclays.com",
    "Deutsche Bank": "https://www.db.com",
    "UBS": "https://www.ubs.com",
    "Wells Fargo": "https://www.wellsfargo.com",
    "Piper Sandler": "https://www.pipersandler.com",
    "Raymond James": "https://www.raymondjames.com",
    "BMO Capital": "https://www.bmocm.com",
    "BMO": "https://www.bmocm.com",
    "RBC Capital": "https://www.rbccm.com",
    "RBC": "https://www.rbccm.com",
    "Jefferies": "https://www.jefferies.com",
    "Oppenheimer": "https://www.oppenheimer.com",
    "Needham": "https://www.needhamco.com",
    "Wedbush": "https://www.wedbush.com",
    "Stifel": "https://www.stifel.com",
    "Canaccord": "https://www.canaccordgenuity.com",
    "B. Riley": "https://www.brileyfin.com",
    "Wolfe Research": "https://www.wolferesearch.com",
    "Bernstein": "https://www.bernstein.com",
    "Cowen": "https://www.cowen.com",
    "Evercore": "https://www.evercore.com",
    "Mizuho": "https://www.mizuhogroup.com",
    "HSBC": "https://www.hsbc.com",
    "Truist": "https://www.truist.com",
    "KeyBanc": "https://www.key.com",
    "Baird": "https://www.rwbaird.com",
    "Guggenheim": "https://www.guggenheimpartners.com",
    "Northland Capital Markets": "https://www.northlandcm.com",
    "Rosenblatt": "https://www.rblt.com",
    "Scotiabank": "https://www.scotiabank.com",
    "TD Cowen": "https://www.cowen.com",
    "Citigroup": "https://www.citigroup.com",
    "BofA Securities": "https://www.bankofamerica.com",
    "ARK Invest": "https://www.ark-invest.com",
    "Hindenburg Research": "https://hindenburgresearch.com",
    "Citron Research": "https://citronresearch.com",
    "Motley Fool": "https://www.fool.com",
}


def get_firm_url(firm_name: str | None) -> str | None:
    """Look up the URL for a firm name. Returns None if not found."""
    if not firm_name:
        return None
    return FIRM_URLS.get(firm_name)
