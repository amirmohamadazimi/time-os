import { useQuery, useQueryClient } from "@tanstack/react-query";
import { endpoints } from "../api/endpoints";

export const CALENDAR_KEYS = [["calendar-accounts"], ["calendar-events"], ["calendar-free"]] as const;

/** Refresh calendar feeds when a calendar view opens, unless they were synced in the last 15 minutes. */
export function useCalendarAutoSync(enabled = true) {
  const qc = useQueryClient();
  return useQuery({
    queryKey: ["calendar-sync"],
    queryFn: async () => {
      const results = await endpoints.syncCalendars({ max_age_s: 900 });
      if (results.some((r) => r.status !== "skipped")) {
        CALENDAR_KEYS.forEach((queryKey) => qc.invalidateQueries({ queryKey }));
      }
      return results;
    },
    enabled,
    staleTime: 5 * 60_000,
    retry: false,
  });
}
