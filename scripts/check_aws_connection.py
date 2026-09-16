import boto3

def main() -> None:
    session = boto3.Session()

    if session.region_name is None:
        raise RuntimeError("Região AWS não configurada.")

    identity = session.client("sts").get_caller_identity()
    principal_type = identity["Arn"].split(":")[-1].split("/")[0]

    print("Autenticação AWS realizada com sucesso.")
    print(f"Região: {session.region_name}")
    print(f"Tipo de identidade: {principal_type}")


if __name__ == "__main__":
    main()
