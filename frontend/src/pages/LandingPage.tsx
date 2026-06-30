import { AudienceSection } from "../components/landing/AudienceSection";
import { ArchitectureSection } from "../components/landing/ArchitectureSection";
import { ChipSection } from "../components/landing/ChipSection";
import { ComparisonSection } from "../components/landing/ComparisonSection";
import { ExampleSection } from "../components/landing/ExampleSection";
import { FinalCta } from "../components/landing/FinalCta";
import { Hero } from "../components/landing/Hero";
import { RedactionContextSection } from "../components/landing/RedactionContextSection";
import { WorkflowSection } from "../components/landing/WorkflowSection";

const INFORMATION_TYPES = [
  "Namen",
  "Adressen",
  "Orte",
  "Organisationen",
  "E-Mail-Adressen",
  "Telefonnummern",
  "IBANs",
  "Aktenzeichen",
  "Vertragsnummern",
  "Kundennummern",
  "Rechnungsnummern",
  "Datumsangaben",
  "Versicherungs- und Schadennummern",
  "weitere domänenspezifische Kennzeichen",
] as const;

const FILE_FORMATS = [
  "PDF",
  "Word-Dokumente",
  "Bilder und Scans",
  "Textdateien",
  "CSV und JSON",
  "weitere strukturierte Formate",
] as const;

export default function LandingPage() {
  return (
    <main className="bg-[linear-gradient(to_bottom,#F5F6F1,#EEF2EA)]">
      <div className="mx-auto flex max-w-4xl flex-col gap-16 px-4 py-16 sm:py-20">
        <Hero />
        <RedactionContextSection />
        <ComparisonSection />
        <WorkflowSection />
        <ExampleSection />
        <ChipSection title="Unterstützte Informationsarten" items={INFORMATION_TYPES} />
        <ChipSection
          title="Dateiformate"
          intro="Geplant sind Workflows für:"
          items={FILE_FORMATS}
        />
        <AudienceSection />
        <ArchitectureSection />
        <FinalCta />
      </div>
    </main>
  );
}
