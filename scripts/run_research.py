import json
from app.services.research import research_company

def main():
    print("Executing live research on https://www.meetuniversity.com...")
    result = research_company(
        company_name="Meet University",
        url="https://www.meetuniversity.com"
    )

    print("\n" + "=" * 60)
    print("LIVE RESEARCH RESULTS")
    print("=" * 60)
    print("Company:", result["company"]["name"])
    print("Crawled Pages Count:", result["crawled_pages_count"])
    print("Search Results Count:", result["search_results_count"])
    print("\nExtracted Profile Fields:")
    for pf in result["profile_fields"]:
        status = pf["status"].upper()
        print(f"\n[{status}] {pf['key'].upper()}:")
        print(f"  Value: {pf['value']}")
        print(f"  Verified Fact: {pf['is_verified_fact']}")
        print(f"  Source URL: {pf['source_url']}")
        if pf.get("evidence_snippet"):
            print(f"  Evidence Snippet: {pf['evidence_snippet'][:120]}...")
        else:
            print("  Evidence Snippet: None (Assumption)")

    print("=" * 60)

if __name__ == "__main__":
    main()
