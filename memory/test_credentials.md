# ChipSutra Test Credentials

## Admin Account
- Email: `admin@chipsutra.ai`
- Password: `3BmYkUvpksleU@KQ4nwa`
- Role: `admin`

## Test User (for signup testing)
- Email: `engineer@test.com`
- Password: `Test@1234`
- Role: `user`

## Auth Endpoints
- `POST /api/auth/register` — email, password, name
- `POST /api/auth/login` — email, password (returns `access_token`)
- `GET /api/auth/me` — Bearer token in `Authorization` header
- `POST /api/auth/logout`

## Auth Method
JWT bearer token stored in `localStorage` as `chipsutra_token`.
All authenticated API calls send `Authorization: Bearer <token>`.
