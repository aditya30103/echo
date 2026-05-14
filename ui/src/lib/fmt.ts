const MONTHS = ['Jan','Feb','Mar','Apr','May','Jun','Jul','Aug','Sep','Oct','Nov','Dec'];

/**
 * Formats an ISO date string as "14 May 25".
 * Accepts full datetime ("2025-05-14T..."), date-only ("2025-05-14"),
 * or month-only ("2025-05") → "May 25".
 */
export function fmtDate(iso: string | undefined | null): string {
    if (!iso) return '';
    const datePart = iso.split('T')[0];
    const parts = datePart.split('-');
    const year  = (parts[0] ?? '').slice(2);
    const month = MONTHS[parseInt(parts[1] ?? '0') - 1] ?? '';
    const day   = parts[2] ? String(parseInt(parts[2])) : '';
    return day ? `${day} ${month} ${year}` : `${month} ${year}`;
}
