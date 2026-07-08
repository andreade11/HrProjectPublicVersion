# main.py
from env_loader import load_env_file

load_env_file()

# ----------------------------
# CONFIG (temporary)
# ----------------------------
# https://tally.so/r/PdzVy0
#https://job-boards.eu.greenhouse.io/imc/jobs/4740839101?gh_src=aee47bb2teu  american with both education and experience
#https://job-boards.eu.greenhouse.io/imc/jobs/4727082101?gh_src=aee47bb2teu just education
JOB_URL = "https://career2.successfactors.eu/careers?career_ns=job_application&company=MigrosP1&career_job_req_id=911&lang=de_DE#_gl=1*1kzy78r*_gcl_aw*R0NMLjE3NzQwMTkzNzQuQ2owS0NRanc0UFBOQmhEOEFSSXNBTW8taWN5UHNYODhJMWdMS2ZfdVV2MkJ1OVVKeVBLajhldWpLV3ZTRFZBX0ZWVi04dnBaZUNVdUJ5UWFBdXViRUFMd193Y0I.*_gcl_au*MTMwMDQzNzQ4Ny4xNzc0MDE5Mzc0*_ga*Mjg2ODE2Mjg0LjE3NzQwMTkzNzQ.*_ga_PH8HPPFGL0*czE3NzQwMTkzNzQkbzEkZzEkdDE3NzQwMTk0MzMkajEkbDAkaDA." 
PRODUCTION_MODE = "Yes"
DEFAULT_APPLICATION_LANGUAGE = "fr"
#https://redalpine.jobs.personio.com/job/2510146?display=en#apply
#generalats: https://swissroc.welcomekit.co/companies/swissroc/jobs/analyste-asset-management-h-f
#successfactor: https://career2.successfactors.eu/career?company=jetaviation&site=&lang=en_US&requestParams=V1uYhb3AY4%2fysv2GLtCD3r6zN9542m1RTW8TMRA1aaKkFEGrSty47DmKyDYhUThAVKmliEpIpVwq%0atEy9k8SNY7vj2XwoKr8IfgTijgRH%2fgDiwH%2fAWyI1C%2fXBsmfezHtv5uNvUfEkdi5gCo2MlW68AD86%0aBlep%2fvj85eH7bxuidCDuagvpAUi2dCQ2eUToR1anc%2ffsucjPvVkt3Nv5i0XZK8aMxO7Zq%2buuGsyw%0accKkzPDpp%2b9vf%2f56tDwsCTF3AX6HhWBRk1qh4aM0uxQfxMbfeO3Cnvt4hucsdiQQIiUhkhBeJqoA%0aLLfjdovFlrdSge47pxfr6coAtMeQD9WvlUOtDK7nqy8DT0OOWNyXlgg1sLImKYrZanaexJ1uK249%0ajgNQ%2bSPDSAb0qUe6ja0q7cSBuVFSyhUgw1Rd9%2f%2f3t7myaPx6twe5YwiOlFzhyvk0C4RoktMTFtth%0aI7O%2bRuJ9QmBMb1O1S5NxkgXJiSMcIKGRhVl8XUaDzMicCvS%2btWOFPuqdvatHDmlgaQKhoBCHdBoo%0alQ%2fLvYkvo5X7qBcdWjvU%2bAaGx2BgiBTVIzlCOcY06jWv6v9D%2b4F6wUr6IjJwSZsZpgUvHAa0daxM%0awKTBLM6dopy62enuddvdvXYnbjav5n8AE%2fDf8A%3d%3d&login_ns=register&career_ns=job%5fapplication&career_job_req_id=5254&jobPipeline=Jobs.ch&clientId=jobs2web&_s.crb=RQdM%2bFgcQrPNl2SpiznR8rC6QxXp%2b34S%2f9EV9jJHsG8%3d

#https://jobs.ashbyhq.com/mentis/146b4df9-c4f2-4145-b110-cb10a266c303/application?utm_source=LinkedInManual

#"Jet aviation" is for successfactors ex. https://career2.successfactors.eu/career?company=jetaviation&site=&lang=en_US&requestParams=V1uYhb3AY4%2fysv2GLtCD3r6zN9542m1RTW8TMRA1aaKkFEGrSty47DmKyDYhUThAVKmliEpIpVwq%0atEy9k8SNY7vj2XwoKr8IfgTijgRH%2fgDiwH%2fAWyI1C%2fXBsmfezHtv5uNvUfEkdi5gCo2MlW68AD86%0aBlep%2fvj85eH7bxuidCDuagvpAUi2dCQ2eUToR1anc%2ffsucjPvVkt3Nv5i0XZK8aMxO7Zq%2buuGsyw%0accKkzPDpp%2b9vf%2f56tDwsCTF3AX6HhWBRk1qh4aM0uxQfxMbfeO3Cnvt4hucsdiQQIiUhkhBeJqoA%0aLLfjdovFlrdSge47pxfr6coAtMeQD9WvlUOtDK7nqy8DT0OOWNyXlgg1sLImKYrZanaexJ1uK249%0ajgNQ%2bSPDSAb0qUe6ja0q7cSBuVFSyhUgw1Rd9%2f%2f3t7myaPx6twe5YwiOlFzhyvk0C4RoktMTFtth%0aI7O%2bRuJ9QmBMb1O1S5NxkgXJiSMcIKGRhVl8XUaDzMicCvS%2btWOFPuqdvatHDmlgaQKhoBCHdBoo%0alQ%2fLvYkvo5X7qBcdWjvU%2bAaGx2BgiBTVIzlCOcY06jWv6v9D%2b4F6wUr6IjJwSZsZpgUvHAa0daxM%0awKTBLM6dopy62enuddvdvXYnbjav5n8AE%2fDf8A%3d%3d&login_ns=register&career_ns=job%5fapplication&career_job_req_id=5254&jobPipeline=Jobs.ch&clientId=jobs2web&_s.crb=RQdM%2bFgcQrPNl2SpiznR8rC6QxXp%2b34S%2f9EV9jJHsG8%3d

#"Takeda" is for workdays : https://takeda.wd3.myworkdayjobs.com/en-US/External/job/Lodz-Poland/M-A-Project-Lead_R0173890/apply/applyManually?utm_campaign=direc-traffic&utm_medium=referral&utm_source=takeda.com&utm_id=takeda-global-en
# JOBUP : https://www.jobup.ch/en/application/create/88fcaeae-0ea2-49a2-b175-33e9fdbdab3c/ OR https://www.jobup.ch/en/application/create/88e3efe4-370c-46ab-9a39-fdb834209e13/

#for greenhouse JOB_URL = "https://job-boards.eu.greenhouse.io/imc/jobs/4667853101?gh_src=aee47bb2teu"

def detect_ats(url: str) -> str:
    url = url.lower()
    if "greenhouse.io" in url:
        return "greenhouse"
    elif "smartrecruiters" in url:
        return "smartrecruiters"
    elif "workday" in url:
        return "workday"
    elif "successfactors" in url:
        return "successfactors"
    elif "jobup.ch" in url:
        return "jobup"
    else:
        print("what ?")
        return "unknown"


def dispatch(ats: str, url: str):
    if ats == "greenhouse":
        import greenhouse
        greenhouse.run(url)
    elif ats == "smartrecruiters":
        import smartrecruiters
        smartrecruiters.run(url)
    elif ats == "workday":
        import workday
        workday.run(url)
    elif ats == "successfactors":
        import successfactors
        successfactors.run(url)
    elif ats == "jobup":
        import jobup
        jobup.run(url)
    elif ats =="unknown":
        print("LAUNCH1")
        try:
            import generalats
            generalats.run(url)
            print("LAUNCH2")
        except Exception as exc:
            print("GENERALATS ERROR:", exc)


def normalize_production_mode(value: str) -> str:
    lowered = (value or "").strip().lower()
    if lowered in {"yes", "true", "1", "on"}:
        return "Yes"
    if lowered in {"no", "false", "0", "off"}:
        return "No"
    raise SystemExit("--mode must be Yes or No")

if __name__ == "__main__":
    import argparse
    import json
    import sys
    import os
    from language_context import detect_application_language

    parser = argparse.ArgumentParser()
    parser.add_argument("url", nargs="?", default="")
    parser.add_argument("job_key", nargs="?", default="")
    parser.add_argument("--mode", default="")
    parser.add_argument("--answers-json", default="")
    args = parser.parse_args()

    url = (args.url or "").strip() or JOB_URL
    production_mode = normalize_production_mode((args.mode or "").strip() or PRODUCTION_MODE)

    if args.job_key.strip():
        os.environ["JOB_KEY"] = args.job_key.strip()

    os.environ["PRODUCTION_MODE"] = production_mode
    application_language = detect_application_language(url, default=DEFAULT_APPLICATION_LANGUAGE)
    os.environ["APP_LANGUAGE"] = application_language

    if args.answers_json.strip():
        # Validate payload early so ATS modules receive a clean object string.
        try:
            payload = json.loads(args.answers_json)
        except Exception as exc:
            raise SystemExit(f"--answers-json must be a valid JSON object: {exc}")
        if not isinstance(payload, dict):
            raise SystemExit("--answers-json must be a JSON object like {\"q_x\":\"answer\"}")
        os.environ["JOB_ANSWERS_JSON"] = json.dumps(payload, ensure_ascii=False)

    ats = detect_ats(url)
    print("Detected ATS:", ats)
    print("Production mode:", production_mode)
    print("Application language:", application_language)
    dispatch(ats, url)
