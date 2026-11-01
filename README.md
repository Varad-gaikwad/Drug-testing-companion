# Digital Companion for Field Drug Testing

A phone-camera web app that reads the colour reaction of a **Marquis colorimetric drug test kit**, classifies it with machine learning, and saves every result in a **tamper-evident log**.

**Live demo:** [[https://YOUR-SERVICE-NAME.onrender.com](https://drug-testing-companion-2.onrender.com)
*(Free hosting: the first load can take about a minute while the server wakes up. Demo data may reset on restart.)*

> **Smart India Hackathon 2026** · Team **Tech Catalysts** (Team ID 12) · Problem Statement 26231 · MedTech / BioTech / HealthTech · Software

---

## Why we built it

Field drug test kits work by colour change, and officers judge that colour by eye. That is subjective, depends on lighting, and leaves no verifiable record. This app standardises the reading and makes every result traceable, using only the kit and a phone the officer already has.


**Who benefits:** field officers (faster, standardised screening), supervisors (a traceable log) and the legal process (records that can be verified).

> This is a screening aid. Every positive result is presumptive and still needs lab confirmation.
## What it does

- Officer signs up and logs in.
- Photographs the kit's colour reaction using the phone camera.
- Gets an instant result: **POSITIVE** (presumptive substance), **NEGATIVE**, or **INCONCLUSIVE**.
- Saves the result with a timestamp, officer ID and GPS location.
- Anyone can verify that a record, or the whole log, has not been altered.

## How it works

1. **Capture:** the browser camera and canvas read the reaction colour and convert it to **HSV** values.
2. **Classify:** the HSV values go to `/classify`, where a Random Forest model predicts the substance and a confidence score.
   - Confidence below **0.65** → `INCONCLUSIVE`
   - Label `no_reaction` → `NEGATIVE`
   - Anything else → `POSITIVE` (presumptive, e.g. "Presumptive Positive: MDMA")
3. **Record:** `/record` stores the test with a SHA-256 hash that also includes the **previous record's hash**, forming a chain.
4. **Verify:** `/verify/<id>` recomputes one record's hash. `/verify_chain` walks the whole log. Editing any past record breaks every hash after it.

## Model and dataset

| | |
|---|---|
| Dataset | `synthetic_marquis_dataset.csv`, about 10,000 synthetic samples |
| Source | Generated from published Marquis reagent colour-response literature |
| Input features | H, S, V (hue, saturation, value) |
| Model | scikit-learn Random Forest, saved as `marquis_classifier.joblib` |
| Prototype accuracy | about 92% on synthetic data |
| Known weakness | MDMA and opiate reactions are sometimes confused |

**Limits:** results are *presumptive only*. The data is synthetic, so real forensic validation on actual kit photos is still required before any real use.

## Tech stack

Python · Flask · Flask-CORS · scikit-learn · joblib · SQLite · gunicorn · HTML / JavaScript (camera + canvas) · hosted on Render


## Why it is useful

- **Consistent results:** a trained model reads the colour, so the result depends less on who is looking or how they judge shades.
- **No new hardware:** it works with the colorimetric kits already in use. All it needs is a phone with a camera and a browser, with no app to install.
- **Instant on-site screening:** the officer gets a result in seconds, without waiting for a lab.
- **Honest about uncertainty:** weak or ambiguous reactions are flagged INCONCLUSIVE instead of being forced into a guess.
- **Tamper-evident records:** every test is hash-chained to the one before it, so any later edit is detectable. This strengthens the integrity of the evidence trail.
- **Built-in accountability:** each test is tied to an officer ID, a timestamp and a GPS location, and replaces handwritten notes.
- **Easy to verify:** supervisors or courts can check one record or the whole log with a single request.

## API

| Endpoint | Method | Purpose |
|---|---|---|
| `/signup`, `/login` | POST | Officer accounts (passwords stored hashed) |
| `/classify` | POST | HSV in, outcome + substance out |
| `/record` | POST | Save a result into the hash chain |
| `/records` | GET | List all records |
| `/officer/<id>/tests` | GET | One officer's tests |
| `/verify/<test_id>` | GET | Check a single record |
| `/verify_chain` | GET | Check the entire log |

## Project files

```
backend.py                    Flask API and chain logic
frontend.html / login.html    Camera test screen and login page
marquis_classifier.joblib     Trained model
synthetic_marquis_dataset.csv Training data
requirements.txt              Python dependencies
```


## Roadmap

- Login tokens so record and verify endpoints are protected
- Validation on real kit photos and more reagents
- Persistent database for production use

## Team Tech Catalysts

Varad Gaikwad (leader) · Raunak Tiwari · Dhairya Sommanek · Shubhanshu Agrawal · Vanshika Rathore · Anant Agastya

## License

MIT
