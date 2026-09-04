type TaxonomyKind = "region" | "country" | "service";

type TaxonomyMessageKey =
  | "taxonomy.regions.centralAsia"
  | "taxonomy.regions.asia"
  | "taxonomy.regions.europe"
  | "taxonomy.regions.africa"
  | "taxonomy.regions.northAmerica"
  | "taxonomy.regions.latinAmerica"
  | "taxonomy.countries.uzbekistan"
  | "taxonomy.countries.kazakhstan"
  | "taxonomy.countries.kyrgyzstan"
  | "taxonomy.countries.tajikistan"
  | "taxonomy.countries.turkmenistan"
  | "taxonomy.services.construction"
  | "taxonomy.services.medical"
  | "taxonomy.services.it"
  | "taxonomy.services.industrialServices"
  | "taxonomy.services.consulting"
  | "taxonomy.services.equipmentSupply"
  | "taxonomy.services.other";

const TAXONOMY_KEYS: Readonly<
  Record<TaxonomyKind, Readonly<Record<string, TaxonomyMessageKey>>>
> = {
  region: {
    "Central Asia": "taxonomy.regions.centralAsia",
    Asia: "taxonomy.regions.asia",
    Europe: "taxonomy.regions.europe",
    Africa: "taxonomy.regions.africa",
    "North America": "taxonomy.regions.northAmerica",
    "Latin America": "taxonomy.regions.latinAmerica",
  },
  country: {
    Uzbekistan: "taxonomy.countries.uzbekistan",
    Kazakhstan: "taxonomy.countries.kazakhstan",
    Kyrgyzstan: "taxonomy.countries.kyrgyzstan",
    Tajikistan: "taxonomy.countries.tajikistan",
    Turkmenistan: "taxonomy.countries.turkmenistan",
  },
  service: {
    construction: "taxonomy.services.construction",
    medical: "taxonomy.services.medical",
    IT: "taxonomy.services.it",
    "industrial services": "taxonomy.services.industrialServices",
    consulting: "taxonomy.services.consulting",
    "equipment supply": "taxonomy.services.equipmentSupply",
    other: "taxonomy.services.other",
  },
};

/** Translate known presentation labels while preserving submitted/API values. */
export function localizeTaxonomyValue(
  kind: TaxonomyKind,
  value: string,
  translate: (key: TaxonomyMessageKey) => string,
): string {
  const key = TAXONOMY_KEYS[kind][value];
  return key ? translate(key) : value;
}

/** Localize a known canonical service while preserving provider labels for unknown services. */
export function translateServiceLabel(
  value: string,
  translate: (key: TaxonomyMessageKey) => string,
  fallback: string,
): string {
  const key = TAXONOMY_KEYS.service[value];
  return key ? translate(key) : fallback;
}
