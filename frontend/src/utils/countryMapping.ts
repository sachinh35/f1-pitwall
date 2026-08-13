/**
 * Utility functions for country code to emoji and name mappings
 */

// Country code to flag emoji mapping (ISO 3166-1 alpha-3 to flag emoji)
const FLAG_EMOJI_MAP: { [key: string]: string } = {
    'GBR': '🇬🇧', 'NED': '🇳🇱', 'FRA': '🇫🇷', 'ESP': '🇪🇸', 'GER': '🇩🇪',
    'AUS': '🇦🇺', 'MEX': '🇲🇽', 'CAN': '🇨🇦', 'FIN': '🇫🇮', 'JPN': '🇯🇵',
    'CHN': '🇨🇳', 'DEN': '🇩🇰', 'MON': '🇲🇨', 'THA': '🇹🇭', 'NZL': '🇳🇿',
    'RUS': '🇷🇺', 'POL': '🇵🇱', 'CHE': '🇨🇭', 'AUT': '🇦🇹', 'BEL': '🇧🇪',
    'ITA': '🇮🇹', 'BRA': '🇧🇷', 'ARG': '🇦🇷', 'VEN': '🇻🇪', 'COL': '🇨🇴',
    'SAU': '🇸🇦', 'IND': '🇮🇳', 'SGP': '🇸🇬', 'MYS': '🇲🇾', 'IDN': '🇮🇩',
    'KOR': '🇰🇷', 'ARE': '🇦🇪', 'USA': '🇺🇸', 'IRL': '🇮🇪', 'PRT': '🇵🇹',
    'CZE': '🇨🇿', 'HUN': '🇭🇺', 'SWE': '🇸🇪', 'NOR': '🇳🇴', 'EST': '🇪🇪',
    'LTU': '🇱🇹', 'LVA': '🇱🇻', 'ROU': '🇷🇴', 'BGR': '🇧🇬', 'HRV': '🇭🇷',
    'SVN': '🇸🇮', 'SVK': '🇸🇰', 'ISR': '🇮🇱', 'TUR': '🇹🇷', 'GRC': '🇬🇷',
    'TWN': '🇹🇼', 'HKG': '🇭🇰', 'PHL': '🇵🇭', 'VNM': '🇻🇳', 'ZAF': '🇿🇦',
    'BRN': '🇧🇭', 'KSA': '🇸🇦', 'AZE': '🇦🇿',
};

const COUNTRY_NAME_MAP: { [key: string]: string } = {
    'GBR': 'Great Britain', 'NED': 'Netherlands', 'FRA': 'France', 'ESP': 'Spain', 'GER': 'Germany',
    'AUS': 'Australia', 'MEX': 'Mexico', 'CAN': 'Canada', 'FIN': 'Finland', 'JPN': 'Japan',
    'CHN': 'China', 'DEN': 'Denmark', 'MON': 'Monaco', 'THA': 'Thailand', 'NZL': 'New Zealand',
    'RUS': 'Russia', 'POL': 'Poland', 'CHE': 'Switzerland', 'AUT': 'Austria', 'BEL': 'Belgium',
    'ITA': 'Italy', 'BRA': 'Brazil', 'ARG': 'Argentina', 'VEN': 'Venezuela', 'COL': 'Colombia',
    'SAU': 'Saudi Arabia', 'IND': 'India', 'SGP': 'Singapore', 'MYS': 'Malaysia', 'IDN': 'Indonesia',
    'KOR': 'South Korea', 'ARE': 'UAE', 'USA': 'United States', 'IRL': 'Ireland', 'PRT': 'Portugal',
    'CZE': 'Czech Republic', 'HUN': 'Hungary', 'SWE': 'Sweden', 'NOR': 'Norway', 'EST': 'Estonia',
    'LTU': 'Lithuania', 'LVA': 'Latvia', 'ROU': 'Romania', 'BGR': 'Bulgaria', 'HRV': 'Croatia',
    'SVN': 'Slovenia', 'SVK': 'Slovakia', 'ISR': 'Israel', 'TUR': 'Turkey', 'GRC': 'Greece',
    'TWN': 'Taiwan', 'HKG': 'Hong Kong', 'PHL': 'Philippines', 'VNM': 'Vietnam', 'ZAF': 'South Africa',
    'BRN': 'Bahrain', 'KSA': 'Saudi Arabia', 'AZE': 'Azerbaijan',
};

export const getCountryFlagEmoji = (countryCode: string | null | undefined): string | null => {
    if (!countryCode) {
        return null;
    }
    return FLAG_EMOJI_MAP[countryCode.toUpperCase()] || '🏁';
};

export const getCountryName = (countryCode: string | null | undefined): string | null => {
    if (!countryCode) {
        return null;
    }
    return COUNTRY_NAME_MAP[countryCode.toUpperCase()] || countryCode;
};

