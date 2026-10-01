// Optional "Support this project" link. Set NEXT_PUBLIC_SUPPORT_URL (build time) to an https URL you own;
// when unset or not https, nothing is rendered. No default is provided on purpose.
const raw = process.env.NEXT_PUBLIC_SUPPORT_URL?.trim() ?? "";
export const SUPPORT_URL = /^https:\/\/[^\s]+$/.test(raw) ? raw : "";
