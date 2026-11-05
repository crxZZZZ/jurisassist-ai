import { test, expect, type Page } from "@playwright/test";

const user = {
  id: "demo-user",
  name: "Marina Silva",
  email: "marina@example.test",
  role: "admin",
};
const basis = {
  indexed_sources: 0,
  expected_sources: 3,
  pending_update: false,
  stale: true,
};
async function mockApi(page: Page) {
  // UI contract tests use explicit API fixtures. Real API/worker flows are covered by pytest.
  let loggedIn = false;
  await page.route("**/api/v1/**", async (route) => {
    const path = new URL(route.request().url()).pathname.replace("/api/v1", "");
    let data: unknown = [];
    if (path === "/auth/me") {
      if (!loggedIn)
        return route.fulfill({
          status: 401,
          json: { detail: "Entre para continuar." },
        });
      data = user;
    }
    if (path === "/auth/login") {
      const body = route.request().postDataJSON();
      if (body.password !== "demo-password-123")
        return route.fulfill({
          status: 401,
          json: { detail: "E-mail ou senha inválidos." },
        });
      loggedIn = true;
      data = { user, csrf_token: "ui-test-csrf" };
    }
    if (path === "/auth/logout") {
      loggedIn = false;
      data = { status: "ok" };
    }
    if (path === "/status")
      data = {
        ollama_online: false,
        model_installed: false,
        model: "qwen3:4b",
        basis,
        worker_busy: false,
      };
    if (path === "/admin/overview")
      data = { jobs: [], feedback: [], evaluations: [], basis };
    if (path === "/admin/sources")
      data = [
        {
          id: "clt",
          title: "CLT · Consolidação das Leis do Trabalho",
          url: "https://www.planalto.gov.br/ccivil_03/decreto-lei/del5452compilado.htm",
          checked_at: null,
        },
      ];
    if (path === "/examples")
      data = [
        {
          id: "servicos-ti",
          title: "Prestação de serviços de TI · Exemplo fictício",
          description:
            "Contrato fictício com obrigações e prazos para revisão.",
        },
      ];
    if (path === "/conversations" && route.request().method() === "POST")
      data = { id: "conversation-1", title: "Nova consulta" };
    if (
      path === "/conversations/conversation-1/messages" &&
      route.request().method() === "POST"
    )
      return route.fulfill({
        status: 409,
        json: { detail: "Aguarde a consulta anterior terminar." },
      });
    return route.fulfill({ json: data });
  });
}

async function login(page: Page) {
  await page.goto("/");
  await page.getByLabel("E-mail", { exact: true }).fill(user.email);
  await page.getByLabel("Senha", { exact: true }).fill("demo-password-123");
  await page.getByRole("button", { name: "Entrar no meu espaço" }).click();
  await expect(
    page.getByRole("heading", { name: "Qual é a sua dúvida jurídica?" }),
  ).toBeVisible();
}
async function navigate(page: Page, name: string) {
  const menu = page.getByRole("button", { name: "Abrir menu" });
  if (await menu.isVisible()) await menu.click();
  await page
    .getByRole("navigation")
    .getByRole("button", { name, exact: true })
    .click();
}

test.beforeEach(async ({ page }) => {
  await mockApi(page);
});
test("login errors and authenticated navigation", async ({ page }) => {
  await page.goto("/");
  await page.getByLabel("E-mail", { exact: true }).fill(user.email);
  await page.getByLabel("Senha", { exact: true }).fill("wrong-password");
  await page.getByRole("button", { name: "Entrar no meu espaço" }).click();
  await expect(page.getByRole("alert")).toContainText(
    "E-mail ou senha inválidos",
  );
  await page.getByLabel("Senha", { exact: true }).fill("demo-password-123");
  await page.getByRole("button", { name: "Entrar no meu espaço" }).click();
  await expect(
    page.getByRole("heading", { name: "Qual é a sua dúvida jurídica?" }),
  ).toBeVisible();
  await expect(page.getByText("IA local pendente")).toBeVisible();
  await navigate(page, "Análise de contratos");
  await expect(
    page.getByRole("heading", { name: "Meus contratos", exact: true }),
  ).toBeVisible();
  await expect(
    page.getByRole("button", { name: "Usar este exemplo" }),
  ).toBeVisible();
  await navigate(page, "Biblioteca jurídica");
  await page.getByRole("textbox", { name: "Pesquisar biblioteca" }).fill("CLT");
  await expect(page.getByText("Nenhuma fonte encontrada")).toBeVisible();
  await navigate(page, "Administração");
  await expect(
    page.getByRole("button", { name: "Verificar fonte" }),
  ).toBeVisible();
  await expect(
    page.getByText("Qualidade medida, evolução documentada"),
  ).toBeVisible();
});
test("composer validation and explicit backend failure", async ({ page }) => {
  await login(page);
  const send = page.getByRole("button", { name: "Enviar consulta" });
  await expect(send).toBeDisabled();
  await page.getByLabel("Sua dúvida jurídica").fill("Quem é empregador?");
  await send.click();
  await expect(page.getByRole("alert")).toContainText(
    "Aguarde a consulta anterior terminar.",
  );
  await expect(send).toBeEnabled();
});
test("responsive layout has no horizontal overflow", async ({
  page,
}, testInfo) => {
  await login(page);
  for (const name of [
    "Assistente jurídico",
    "Análise de contratos",
    "Biblioteca jurídica",
    "Administração",
  ]) {
    await navigate(page, name);
    expect(
      await page.evaluate(
        () => document.documentElement.scrollWidth <= window.innerWidth,
      ),
    ).toBeTruthy();
  }
  await navigate(page, "Assistente jurídico");
  await page.screenshot({
    path: `../reports/ui-${testInfo.project.name}.png`,
    fullPage: true,
    animations: "disabled",
  });
});
