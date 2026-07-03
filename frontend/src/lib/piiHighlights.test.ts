import { describe, expect, it } from "vitest";

import type { PiiEntity } from "../api/workstations";
import { buildHighlightSegments } from "./piiHighlights";

function entity(
  id: string,
  text: string,
  start: number,
  end: number,
  score = 0.8,
  entityType = "PERSON",
): PiiEntity {
  return {
    id,
    entity_type: entityType,
    text,
    start_offset: start,
    end_offset: end,
    page_number: null,
    page_start_offset: null,
    page_end_offset: null,
    score,
    recognizer: "TestRecognizer",
  };
}

describe("buildHighlightSegments", () => {
  it("marks a simple entity", () => {
    expect(buildHighlightSegments("Hallo Anna!", [entity("a", "Anna", 6, 10)])).toEqual([
      { kind: "text", text: "Hallo " },
      { kind: "entity", text: "Anna", entity: entity("a", "Anna", 6, 10) },
      { kind: "text", text: "!" },
    ]);
  });

  it("sorts and marks multiple entities", () => {
    const anna = entity("a", "Anna", 0, 4);
    const wien = entity("b", "Wien", 8, 12, 0.8, "LOCATION");
    expect(buildHighlightSegments("Anna in Wien", [wien, anna])).toEqual([
      { kind: "entity", text: "Anna", entity: anna },
      { kind: "text", text: " in " },
      { kind: "entity", text: "Wien", entity: wien },
    ]);
  });

  it("uses Unicode codepoints when an emoji precedes an entity", () => {
    const anna = entity("a", "Anna", 2, 6);
    expect(buildHighlightSegments("🙂 Anna", [anna])).toEqual([
      { kind: "text", text: "🙂 " },
      { kind: "entity", text: "Anna", entity: anna },
    ]);
  });

  it("ignores invalid offsets", () => {
    expect(buildHighlightSegments("Anna", [entity("a", "Anna", -1, 3)])).toEqual([
      { kind: "text", text: "Anna" },
    ]);
  });

  it("ignores entity text mismatches", () => {
    expect(buildHighlightSegments("Anna", [entity("a", "Anne", 0, 4)])).toEqual([
      { kind: "text", text: "Anna" },
    ]);
  });

  it("prefers the higher score for overlapping entities", () => {
    const low = entity("low", "Anna", 0, 4, 0.5);
    const high = entity("high", "Anna Wien", 0, 9, 0.9, "LOCATION");
    const segments = buildHighlightSegments("Anna Wien", [low, high]);
    expect(segments).toEqual([{ kind: "entity", text: "Anna Wien", entity: high }]);
  });

  it("prefers the longer entity when overlapping scores match", () => {
    const short = entity("short", "Anna", 0, 4, 0.8);
    const long = entity("long", "Anna Wien", 0, 9, 0.8, "LOCATION");
    expect(buildHighlightSegments("Anna Wien", [short, long])).toEqual([
      { kind: "entity", text: "Anna Wien", entity: long },
    ]);
  });

  it("uses entity type and id as deterministic final tie breakers", () => {
    const personB = entity("b", "Anna", 0, 4, 0.8, "PERSON");
    const personA = entity("a", "Anna", 0, 4, 0.8, "PERSON");
    const location = entity("z", "Anna", 0, 4, 0.8, "LOCATION");
    expect(buildHighlightSegments("Anna", [personB, personA, location])).toEqual([
      { kind: "entity", text: "Anna", entity: location },
    ]);
    expect(buildHighlightSegments("Anna", [personB, personA])).toEqual([
      { kind: "entity", text: "Anna", entity: personA },
    ]);
  });

  describe("review status", () => {
    it("excludes a rejected (false-positive) entity from the highlighted segments", () => {
      const anna = entity("a", "Anna", 0, 4);
      const segments = buildHighlightSegments("Anna in Wien", [anna], { a: "rejected" });
      expect(segments).toEqual([{ kind: "text", text: "Anna in Wien" }]);
    });

    it("attaches the resolved review status to an accepted/kept entity's segment", () => {
      const anna = entity("a", "Anna", 0, 4);
      const accepted = buildHighlightSegments("Anna", [anna], { a: "accepted" });
      expect(accepted).toEqual([{ kind: "entity", text: "Anna", entity: anna, reviewStatus: "accepted" }]);

      const kept = buildHighlightSegments("Anna", [anna], { a: "kept" });
      expect(kept).toEqual([{ kind: "entity", text: "Anna", entity: anna, reviewStatus: "kept" }]);
    });

    it("renders unresolved entities exactly as before (no status map)", () => {
      const anna = entity("a", "Anna", 0, 4);
      expect(buildHighlightSegments("Anna", [anna])).toEqual([
        { kind: "entity", text: "Anna", entity: anna },
      ]);
      expect(buildHighlightSegments("Anna", [anna], {})).toEqual([
        { kind: "entity", text: "Anna", entity: anna },
      ]);
    });

    it("only excludes the rejected entity, letting an accepted duplicate-span sibling stand", () => {
      const rejected = entity("a", "Anna", 0, 4, 0.9);
      const accepted = entity("b", "Anna", 0, 4, 0.5);
      const segments = buildHighlightSegments("Anna", [rejected, accepted], {
        a: "rejected",
        b: "accepted",
      });
      expect(segments).toEqual([
        { kind: "entity", text: "Anna", entity: accepted, reviewStatus: "accepted" },
      ]);
    });
  });
});
