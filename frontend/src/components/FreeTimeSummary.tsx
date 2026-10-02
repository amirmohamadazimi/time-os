import { Badge, Group, Stack, Text } from "@mantine/core";
import type { FreeTime } from "../api/types";
import { formatDateTime, formatMinutes, formatTime } from "../lib/format";

/** Free and busy time inside working hours for one day, from the connected calendars. */
export function FreeTimeSummary({ free }: { free: FreeTime }) {
  if (!free.working_day) return <Text size="sm" c="dimmed">Not a working day.</Text>;
  return (
    <Stack gap={6}>
      <Group gap="lg">
        <Text size="sm">Free <b>{formatMinutes(free.free_minutes)}</b></Text>
        <Text size="sm">In meetings <b>{formatMinutes(free.busy_minutes)}</b></Text>
      </Group>
      <Group gap={6}>
        {free.free.map((span) => (
          <Badge key={span.start} variant="light" color="teal">
            {formatTime(span.start)}–{formatTime(span.end)}
          </Badge>
        ))}
      </Group>
      {free.busy.map((span) => (
        <Text key={span.start} size="xs" c="dimmed">
          Busy {formatTime(span.start)}–{formatTime(span.end)}: {span.titles.join(", ")}
        </Text>
      ))}
      {free.synced_at && <Text size="xs" c="dimmed">Calendar read {formatDateTime(free.synced_at)}</Text>}
    </Stack>
  );
}
