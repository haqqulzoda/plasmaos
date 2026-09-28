# Context provenance and conflicts

The narrow deterministic context extractor now recognizes this RFP as:

- Title: Communications Consultant
- Buyer/issuer: Town of University Park
- Reference: UP-2012-01
- External deadline: `2012-02-17T16:00:00-05:00`
- Deadline timezone: America/New_York
- Country: United States
- Declared funder: absent

Town of University Park is not used as the tender title, and no funder is fabricated.

Each returned field has one of four provenance states:

- `SOURCE_DETECTED`: source evidence exists and no user-confirmed value exists.
- `USER_CONFIRMED`: a user-confirmed value exists and source is absent or agrees.
- `USER_OVERRIDE_CONFLICTS_WITH_SOURCE`: confirmed and detected values differ.
- `UNKNOWN`: neither source nor confirmed value exists.

On conflict, the confirmed value remains authoritative customer data while the source value, document version, page, and evidence span are returned for review. No GET mutates the context, and reprocessing updates only provisional source suggestions. The tests cover equal values, different values, source absent, confirmed absent, and no silent overwrite.

The source deadline remains the historically correct February 17, 2012 at 4:00 PM Eastern time. It is never shifted to manufacture a current downstream workflow. The UI identifies the source deadline as passed while keeping any private internal target date separate.
