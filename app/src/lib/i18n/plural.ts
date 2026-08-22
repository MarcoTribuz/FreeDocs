type Forms = Partial<Record<Intl.LDMLPluralRule, string>> & { other: string };

const rules = new Map<string, Intl.PluralRules>();
const numbers = new Map<string, Intl.NumberFormat>();

/**
 * Pick a form by the locale's own rules, and put the count in it.
 *
 * This exists to kill "(s)". "3 finding(s)" is not English, and the dodge does
 * not survive translation either: French puts zero in the singular — "0 valeur
 * trouvée" — so a hardcoded plural is wrong for one of the four languages on a
 * number this window displays constantly.
 *
 * Forms are named rather than positional, so a language that does not use one
 * simply omits it: Italian never selects `zero`, and passing it would be
 * ignored rather than silently used for the wrong count.
 *
 * Both `Intl` objects are cached because constructing them costs more than the
 * lookup, and the review header formats a count on every keystroke.
 */
export function plural(locale: string, n: number, forms: Forms): string {
	let rule = rules.get(locale);
	if (!rule) rules.set(locale, (rule = new Intl.PluralRules(locale)));
	let format = numbers.get(locale);
	if (!format) numbers.set(locale, (format = new Intl.NumberFormat(locale)));
	const form = forms[rule.select(n)] ?? forms.other;
	return form.split('{n}').join(format.format(n));
}
