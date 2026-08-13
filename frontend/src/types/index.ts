/**
 * Type definitions for F1 Dashboard
 */

export interface Race {
    session_key: number;
    location: string;
    session_name: string;
    country_code: string;
}

export interface EnrichedF1SessionResult {
    dnf: boolean;
    dns: boolean;
    dsq: boolean;
    driver_number: number;
    number_of_laps: number | null;
    meeting_key: number | string;
    session_key: number;
    duration: number | null;
    gap_to_leader: number | string | null;
    position: number | null;
    full_name: string;
    name_acronym: string;
    first_name: string;
    last_name: string;
    country_code: string | null;
}

