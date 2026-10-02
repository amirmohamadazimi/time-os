import { Button, Center, Paper, PasswordInput, Stack, Text, Title } from "@mantine/core";
import { useState } from "react";
import { setToken } from "../api/client";

/** Shown when the server requires an access token (TIMEOS_API_TOKEN) and this browser has none or a wrong one. */
export function TokenGate({ rejected }: { rejected: boolean }) {
  const [value, setValue] = useState("");
  return (
    <Center mih="100vh" p="md">
      <Paper withBorder p="xl" w={420} maw="100%">
        <form onSubmit={(e) => {
          e.preventDefault();
          setToken(value.trim() || null);
          window.location.reload();
        }}>
          <Stack>
            <Title order={3}>Time OS</Title>
            <Text size="sm" c="dimmed">
              This server needs its access token (the TIMEOS_API_TOKEN value). It is saved in this browser only.
            </Text>
            <PasswordInput label="Access token" value={value} onChange={(e) => setValue(e.currentTarget.value)}
              error={rejected ? "That token was not accepted" : undefined} data-autofocus required />
            <Button type="submit">Continue</Button>
          </Stack>
        </form>
      </Paper>
    </Center>
  );
}
