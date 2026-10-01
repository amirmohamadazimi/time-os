import { Button, Group, Paper, Progress, Stack, Text, Title } from "@mantine/core";
import { IconPlayerPause, IconPlayerPlay, IconPlayerSkipForward, IconPlayerStop, IconCheck } from "@tabler/icons-react";
import { useState } from "react";
import { endpoints } from "../api/endpoints";
import type { LiveSession } from "../api/types";
import { useAppMutation } from "../hooks/useFocus";
import { formatClock } from "../lib/format";
import { remainingSeconds } from "../lib/timer";
import { FinishSessionModal } from "./FinishSessionModal";

export function TimerPanel({ session, active, large = false }: { session: LiveSession; active: number; large?: boolean }) {
  const [ending, setEnding] = useState<"completed" | "stopped" | "skipped" | null>(null);
  const pause = useAppMutation(endpoints.pauseFocus);
  const resume = useAppMutation(endpoints.resumeFocus);
  const remaining = remainingSeconds(session, active);
  const progress = session.planned_duration_s ? Math.min(100, (active / session.planned_duration_s) * 100) : null;
  const paused = session.state === "paused";
  return (
    <Paper withBorder p={large ? "xl" : "md"}>
      <Stack gap="xs" align={large ? "center" : "stretch"}>
        <Text size="xs" c="dimmed" tt="uppercase" fw={600}>
          {session.type === "rest" ? "Break" : "Current task"}{paused ? " · paused" : ""}
        </Text>
        <Text fw={600} size={large ? "xl" : "md"}>
          {session.task_title_snapshot ?? (session.type === "rest" ? "Rest" : "Untitled work session")}
        </Text>
        <Title order={large ? 1 : 2} ff="monospace" c={paused ? "yellow" : undefined} style={large ? { fontSize: 64 } : undefined}>
          {formatClock(active)}
        </Title>
        {remaining !== null && (
          <Text size="sm" c="dimmed">
            {remaining >= 0 ? `${formatClock(remaining)} left of ${Math.round(session.planned_duration_s! / 60)} min`
              : `${formatClock(-remaining)} over plan`}
          </Text>
        )}
        {progress !== null && <Progress value={progress} w="100%" color={progress >= 100 ? "teal" : "indigo"} />}
        <Group justify={large ? "center" : "flex-start"} mt="xs">
          {paused ? (
            <Button leftSection={<IconPlayerPlay size={16} />} onClick={() => resume.mutate(undefined)} loading={resume.isPending}>
              Resume
            </Button>
          ) : (
            <Button variant="light" leftSection={<IconPlayerPause size={16} />} onClick={() => pause.mutate(undefined)}
              loading={pause.isPending}>
              Pause
            </Button>
          )}
          <Button color="teal" leftSection={<IconCheck size={16} />} onClick={() => setEnding("completed")}>
            {session.type === "rest" ? "Done" : "Finish"}
          </Button>
          <Button variant="default" leftSection={<IconPlayerStop size={16} />} onClick={() => setEnding("stopped")}>Stop</Button>
          {session.type === "rest" && (
            <Button variant="subtle" leftSection={<IconPlayerSkipForward size={16} />} onClick={() => setEnding("skipped")}>
              Skip
            </Button>
          )}
        </Group>
      </Stack>
      <FinishSessionModal session={session} active={active} endReason={ending} onClose={() => setEnding(null)} />
    </Paper>
  );
}
