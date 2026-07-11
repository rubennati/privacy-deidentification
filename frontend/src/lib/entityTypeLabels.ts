// User-facing German labels for backend entity-type identifiers. The backend enum stays the
// technical source of truth (dev view shows it verbatim); this map only affects user-view display.
// An unknown type falls back to its identifier so a new backend type is never hidden or mislabeled.
const ENTITY_TYPE_LABELS: Record<string, string> = {
  PERSON: "Person",
  EMAIL_ADDRESS: "E-Mail-Adresse",
  PHONE_NUMBER: "Telefonnummer",
  LOCATION: "Ort",
  ORGANIZATION: "Organisation",
  ADDRESS: "Adresse",
  DATE_TIME: "Datum",
  IBAN_CODE: "IBAN",
  BIC: "BIC",
  URL: "Web-Adresse",
  IP_ADDRESS: "IP-Adresse",
  CREDIT_CARD: "Kreditkartennummer",
  UID_AT: "UID-Nummer",
  FN_AT: "Firmenbuchnummer",
  SVNR_AT: "SV-Nummer",
  TAX_ID_AT: "Steuernummer",
  LICENSE_PLATE_AT: "Kfz-Kennzeichen",
  ID_CARD_NUMBER: "Ausweisnummer",
  PASSPORT_NUMBER: "Reisepassnummer",
  CUSTOMER_NUMBER: "Kundennummer",
  CONTRACT_NUMBER: "Vertragsnummer",
  INVOICE_NUMBER: "Rechnungsnummer",
  OFFER_NUMBER: "Angebotsnummer",
  POLICY_NUMBER: "Polizzennummer",
  CLAIM_NUMBER: "Schadensnummer",
  CASE_NUMBER: "Aktenzeichen",
  FILE_REFERENCE: "Geschäftszahl",
  REPORT_NUMBER: "Berichtsnummer",
  ASSESSMENT_NUMBER: "Bescheidnummer",
  TRANSACTION_ID: "Transaktionsnummer",
  PROJECT_ID: "Projektnummer",
  USER_ID: "Benutzerkennung",
  CUSTOMER_LINE: "Kundenzeile",
  CONTACT_LINE: "Kontaktzeile",
};

export function entityTypeLabel(entityType: string): string {
  return ENTITY_TYPE_LABELS[entityType] ?? entityType;
}
