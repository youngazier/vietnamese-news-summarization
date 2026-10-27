# Frontend Guidelines

- Use React, Vite, TypeScript, Tailwind CSS v4, and shadcn/ui with Base UI.
- Before adding shadcn components, read `components.json` and follow the installed shadcn skill.
- Keep page composition, reusable components, and mock data in separate files.
- Use semantic HTML and accessible controls.
- Design mobile-first and verify both mobile and desktop layouts.
- Use Vietnamese text and realistic Vietnamese news mock data.
- Include loading, empty, and error states where applicable.
- Never expose backend credentials in frontend code.
- After changes, run `npm run lint` and `npm run build` from `frontend/`.
- Inspect changed pages with Playwright and check for browser console errors.
