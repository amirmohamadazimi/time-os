import { Button, Checkbox, Group, Modal, Radio, Stack, Text, Textarea } from "@mantine/core";
import { useEffect, useState } from "react";
import { endpoints } from "../api/endpoints";
import type { LiveSession } from "../api/types";
import { useAppMutation } from "../hooks/useFocus";
import { formatClock } from "../lib/format";

type EndReason = "completed" | "stopped" | "skipped";

/** "How did it go?" — records the outcome of the session (and optionally completes the task). */
export function FinishSessionModal({
  session, active, endReason, onClose,
}: { session: LiveSession; active: number; endReason: EndReason | null; onClose: () => void }) {
  const [outcome, setOutcome] = useState<string>("completed");
  const [notes, setNotes] = useState(session.notes ?? "");
  const [completeTask, setCompleteTask] = useState(true);
  useEffect(() => {
    if (endReason) {
      setOutcome(endReason === "completed" ? "completed" : "partial");
      setNotes(session.notes ?? "");
      setCompleteTask(endReason === "completed");
    }
  }, [endReason, session.notes]);
  const finish = useAppMutation(endpoints.finishFocus, onClose);
  const isWork = session.type === "work";
  return (
    <Modal opened={endReason !== null} onClose={onClose} title={isWork ? "How did it go?" : "End break"}>
      <Stack>
        <Text size="sm" c="dimmed">
          {session.task_title_snapshot ?? (isWork ? "Untitled work" : "Break")} · {formatClock(active)} active
        </Text>
        {isWork && (
          <Radio.Group value={outcome} onChange={setOutcome}>
            <Stack gap={6}>
              <Radio value="completed" label="Completed" />
              <Radio value="partial" label="Partially completed" />
              <Radio value="blocked" label="Blocked" />
              <Radio value="abandoned" label="Abandoned" />
            </Stack>
          </Radio.Group>
        )}
        <Textarea label="Optional note" autosize minRows={2} value={notes} onChange={(e) => setNotes(e.currentTarget.value)} />
        {isWork && session.task_id && (
          <Checkbox label="Mark the task as done" checked={completeTask && outcome === "completed"}
            disabled={outcome !== "completed"} onChange={(e) => setCompleteTask(e.currentTarget.checked)} />
        )}
        <Group justify="flex-end">
          <Button variant="default" onClick={onClose}>Keep going</Button>
          <Button loading={finish.isPending} onClick={() => finish.mutate({
            end_reason: endReason ?? "completed",
            outcome: isWork ? outcome : null,
            notes: notes.trim() || null,
            complete_task: isWork && outcome === "completed" && completeTask,
          })}>
            Log session
          </Button>
        </Group>
      </Stack>
    </Modal>
  );
}
