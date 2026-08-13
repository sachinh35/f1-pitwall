import axios from 'axios';
import { LapComparisonData, TeamRadioClip } from '../types/raceMode';

const API_BASE_URL = 'http://localhost:8000';

export const getYears = async () => {
    const response = await axios.get(`${API_BASE_URL}/years`);
    return response.data.years_list;
};

export const getRacesForYear = async (year: number) => {
    const response = await axios.get(`${API_BASE_URL}/races/${year}`);
    return response.data.all_races;
};

export const getSessionResults = async (session_key: number) => {
    const response = await axios.get(`${API_BASE_URL}/session-results/${session_key}`);
    return response.data.results;
};

export interface LapData {
    meeting_key: number;
    session_key: number;
    driver_number: number;
    lap_number: number;
    date_start: string | null;
    duration_sector_1: number | null;
    duration_sector_2: number | null;
    duration_sector_3: number | null;
    lap_duration: number | null;
    i1_speed: number | null;
    i2_speed: number | null;
    st_speed: number | null;
    is_pit_out_lap: boolean;
    segments_sector_1: (number | null)[] | null;
    segments_sector_2: (number | null)[] | null;
    segments_sector_3: (number | null)[] | null;
}

export interface GetSessionLapDataResponse {
    session_key: number;
    lap_data: LapData[];
}

export const getSessionLapData = async (session_key: number, driver_numbers: number[]): Promise<LapData[]> => {
    const response = await axios.post<GetSessionLapDataResponse>(
        `${API_BASE_URL}/session-lap-data/${session_key}`,
        { driver_numbers }
    );
    return response.data.lap_data;
};

export interface Stint {
    meeting_key: number;
    session_key: number;
    driver_number: number;
    stint_number: number;
    lap_start: number;
    lap_end: number;
    compound: string | null;
    tyre_age_at_start: number | null;
}

export const getSessionStints = async (session_key: number): Promise<Stint[]> => {
    const response = await axios.get(`${API_BASE_URL}/session-stints/${session_key}`);
    return response.data.stints as Stint[];
};

export interface RaceControlEvent {
    session_key: number;
    date: string;
    category: string;
    message: string;
    scope: string | null;
    sector: number | null;
    driver_number: number | null;
    flag: string | null;
}

export const getSessionRaceControlEvents = async (session_key: number): Promise<RaceControlEvent[]> => {
    const response = await axios.get(`${API_BASE_URL}/session-race-control-events/${session_key}`);
    return response.data.events as RaceControlEvent[];
};

export interface ConfirmedRosterEntry {
    driver_number: number;
    tla: string;
    full_name: string;
    team_name: string;
    team_colour?: string;
}

export interface StartStreamRequest {
    access_token?: string;
    refresh_token?: string;
    cookies?: string;
    confirmed_roster?: ConfirmedRosterEntry[];
}

export interface AuthenticateRequest {
    email: string;
    password: string;
}

export interface AuthenticateResponse {
    success: boolean;
    access_token: string;
    cookies?: string;
    message?: string;
}

export interface StartStreamResponse {
    success: boolean;
    message: string;
    stream_id: string;
    log_file: string;
}

export const authenticateF1TV = async (email: string, password: string): Promise<AuthenticateResponse> => {
    const response = await axios.post<AuthenticateResponse>(
        `${API_BASE_URL}/authenticate-f1tv`,
        {
            email,
            password
        } as AuthenticateRequest
    );
    return response.data;
};

export const startLiveStream = async (
    accessToken?: string,
    refreshToken?: string,
    cookies?: string,
    confirmedRoster?: ConfirmedRosterEntry[]
): Promise<StartStreamResponse> => {
    const response = await axios.post<StartStreamResponse>(
        `${API_BASE_URL}/start-live-stream`,
        {
            access_token: accessToken,
            refresh_token: refreshToken,
            cookies: cookies,
            confirmed_roster: confirmedRoster
        } as StartStreamRequest
    );
    return response.data;
};

export interface AttachStreamRequest {
    session_name?: string;
    confirmed_roster?: ConfirmedRosterEntry[];
}

export interface CurrentLiveStreamResponse {
    session_name: string;
    stream_id: string;
    log_file: string;
}

/**
 * Attach the backend to an in-progress standalone capture process
 * (scripts/capture_stream.py) by tailing its raw jsonl file, instead of opening a
 * second, backend-owned SignalR connection. This is the intended way to watch a
 * session the standalone capture is already recording - the capture keeps running
 * independent of the backend/frontend, so a backend restart just re-attaches and
 * catches straight back up.
 */
export const attachLiveStream = async (
    sessionName?: string,
    confirmedRoster?: ConfirmedRosterEntry[]
): Promise<StartStreamResponse> => {
    const response = await axios.post<StartStreamResponse>(
        `${API_BASE_URL}/attach-live-stream`,
        {
            session_name: sessionName,
            confirmed_roster: confirmedRoster
        } as AttachStreamRequest
    );
    return response.data;
};

/** Discover the currently-active standalone capture, if any - lets the UI find and
 * (re)connect to it without hardcoding a session name. */
export const getCurrentLiveStream = async (): Promise<CurrentLiveStreamResponse> => {
    const response = await axios.get<CurrentLiveStreamResponse>(`${API_BASE_URL}/live-stream/current`);
    return response.data;
};

export interface SimulateStreamRequest {
    log_file?: string;
    speed_factor?: number;
    confirmed_roster?: ConfirmedRosterEntry[];
}

export const startSimulation = async (request?: SimulateStreamRequest): Promise<StartStreamResponse> => {
    const response = await axios.post<StartStreamResponse>(
        `${API_BASE_URL}/simulate-live-stream`,
        request ?? {}
    );
    return response.data;
};

export interface TokenStatusResponse {
    valid: boolean;
    reason?: string;
    expires_at?: string;
}

export const getF1TvTokenStatus = async (): Promise<TokenStatusResponse> => {
    const response = await axios.get<TokenStatusResponse>(`${API_BASE_URL}/f1tv-token/status`);
    return response.data;
};

export const updateF1TvToken = async (token: string): Promise<TokenStatusResponse> => {
    const response = await axios.post<TokenStatusResponse>(`${API_BASE_URL}/f1tv-token`, { token });
    return response.data;
};

export interface TeamDriverPoolEntry {
    team_name: string;
    driver_number: number | null;
    tla: string | null;
    full_name: string;
    is_reserve: boolean;
}

export interface GetTeamDriverPoolResponse {
    season_year: number;
    drivers: TeamDriverPoolEntry[];
}

export const getTeamDriverPool = async (seasonYear = 2026): Promise<GetTeamDriverPoolResponse> => {
    const response = await axios.get<GetTeamDriverPoolResponse>(`${API_BASE_URL}/team-driver-pool`, {
        params: { season_year: seasonYear }
    });
    return response.data;
};

export const getTeamRadioForSession = async (sessionKey: number): Promise<TeamRadioClip[]> => {
    const response = await axios.get<{ session_key: number; clips: TeamRadioClip[] }>(
        `${API_BASE_URL}/team-radio/${sessionKey}`
    );
    return response.data.clips;
};

export const getLapComparison = async (
    sessionKey: number,
    driverA: number,
    lapA: number,
    driverB: number,
    lapB: number
): Promise<LapComparisonData> => {
    const response = await axios.get<LapComparisonData>(`${API_BASE_URL}/lap-comparison/${sessionKey}`, {
        params: { driver_a: driverA, lap_a: lapA, driver_b: driverB, lap_b: lapB },
    });
    return response.data;
};
