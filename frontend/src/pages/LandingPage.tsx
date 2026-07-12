import { ArchitectureSection } from "../components/landing/ArchitectureSection";
import { AudienceSection } from "../components/landing/AudienceSection";
import { ChipSection } from "../components/landing/ChipSection";
import { ExampleSection } from "../components/landing/ExampleSection";
import { FinalCta } from "../components/landing/FinalCta";
import { FormatsSection } from "../components/landing/FormatsSection";
import { Hero } from "../components/landing/Hero";
import { RedactionContextSection } from "../components/landing/RedactionContextSection";
import { WorkflowSection } from "../components/landing/WorkflowSection";

const INFORMATION_TYPES = [
  "Personennamen, Firmennamen und Anschriften",
  "Orte und Länder",
  "Kundennummern, Vertrags- und Rechnungsnummern, Aktenzeichen",
  "Finanzdaten wie IBAN, Kontonummern, Kreditkartenreferenzen",
  "Versicherungs-, Steuer- und Sozialversicherungsnummern",
  "E-Mail-Adressen, Telefonnummern und Kontaktinformationen",
  "Datum- und Zeitangaben",
  "Weitere branchenspezifische Kennzeichen nach Bedarf",
] as const;

export default function LandingPage() {
  return (
    <div className="mx-auto flex w-full max-w-4xl flex-col gap-16 px-4 py-16 sm:px-6 sm:py-20">
      <Hero />
      <RedactionContextSection />
      <WorkflowSection />
      <ExampleSection />
      <ChipSection title="Welche Datenarten wir erkennen" items={INFORMATION_TYPES} />
      <FormatsSection />
      <AudienceSection />
      <ArchitectureSection />
      <FinalCta />
    </div>
  );
}
