import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useEffect, useRef, useState } from "react";
import { endpoints } from "../api/endpoints";
import type { LiveSession } from "../api/types";
import { liveActiveSeconds } from "../lib/timer";
import { notifyError } from "../lib/notify";

/** Server-authoritative focus timer: the server owns state; the browser only ticks the display. */
export function useCurrentSession() {
  const skew = useRef(0);
  const query = useQuery({
    queryKey: ["focus", "current"],
    queryFn: async () => {
      const session = await endpoints.currentFocus();
      if (session) skew.current = Date.parse(session.server_time) - Date.now();
      return session;
    },
    refetchInterval: 30_000,
  });
  const [active, setActive] = useState(0);
  const session = query.data ?? null;
  useEffect(() => {
    if (!session) return;
    const tick = () => setActive(liveActiveSeconds(session, skew.current, Date.now()));
    tick();
    const id = window.setInterval(tick, 1000);
    return () => window.clearInterval(id);
  }, [session]);
  return { session, active: session ? active : 0, isLoading: query.isLoading };
}

/** Wrap a focus/task mutation so every view refreshes afterwards. */
export function useAppMutation<TArgs, TResult>(fn: (args: TArgs) => Promise<TResult>, onDone?: (r: TResult) => void) {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: fn,
    onSuccess: (result) => {
      qc.invalidateQueries();
      onDone?.(result);
    },
    onError: notifyError,
  });
}

export type { LiveSession };
