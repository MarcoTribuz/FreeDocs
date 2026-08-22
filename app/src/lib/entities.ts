import type { IconName } from './components/icons';

/**
 * Which colour and glyph an entity type is drawn with.
 *
 * A presentation map, not a rule. Nothing here decides what is confidential,
 * what is removed or what is merely flagged — that is `core/policy.py`, and the
 * `action` on each finding is what says so. This file only answers "what should
 * this look like", which is the one question Python has no opinion about.
 *
 * An unknown name falls through to `other` and is still drawn. A build of the
 * engine that gained an entity type must not produce an invisible highlight:
 * the value would be about to be removed and the preview would not show it.
 */
export type EntityCategory =
	| 'person'
	| 'org'
	| 'place'
	| 'financial'
	| 'official'
	| 'contact'
	| 'time'
	| 'role'
	| 'other';

const CATEGORIES: Record<string, EntityCategory> = {
	PERSON: 'person',
	ORGANISATION: 'org',
	LOCATION: 'place',
	ADDRESS: 'place',
	POSTCODE: 'place',
	IBAN: 'financial',
	CREDIT_CARD: 'financial',
	NATIONAL_ID: 'official',
	TAX_ID: 'official',
	VAT_ID: 'official',
	COMPANY_ID: 'official',
	EMAIL: 'contact',
	PHONE: 'contact',
	URL: 'contact',
	IP_ADDRESS: 'contact',
	MAC_ADDRESS: 'contact',
	DATE: 'time',
	AGE: 'time',
	JOB_TITLE: 'role',
	OTHER: 'other'
};

const ICONS: Record<EntityCategory, IconName> = {
	person: 'file-text',
	org: 'file-text',
	place: 'file-text',
	financial: 'file-text',
	official: 'shield-check',
	contact: 'arrow-right',
	time: 'info',
	role: 'info',
	other: 'plus'
};

export function categoryOf(entity: string): EntityCategory {
	return CATEGORIES[entity] ?? 'other';
}

export function iconOf(entity: string): IconName {
	return ICONS[categoryOf(entity)];
}
